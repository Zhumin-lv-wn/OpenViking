# OpenSandbox 沙箱集成技术规范

## 1. 概述

为 vikingbot 添加基于 Alibaba OpenSandbox 的沙箱后端支持，实现：
- 本地 Docker 运行模式
- VKE (火山引擎 Kubernetes) 运行模式
- TOS 共享目录挂载支持

## 2. 架构设计

### 2.1 模块结构

```
vikingbot/
├── sandbox/
│   ├── __init__.py
│   ├── manager.py              # 沙箱生命周期管理（已有）
│   ├── config.py               # 沙箱配置 Schema（已有）
│   ├── base.py                # 沙箱抽象接口（已有）
│   └── backends/
│       ├── __init__.py
│       ├── srt.py              # SRT 后端（已有）
│       ├── docker.py           # Docker 后端（已有框架）
│       └── opensandbox.py      # 【新增】OpenSandbox 后端
```

### 2.2 运行模式

| 模式 | 说明 | 使用场景 |
|------|------|---------|
| `local` | 本地 Docker 运行 | 开发、本地部署 |
| `vke` | VKE Kubernetes 运行 | 生产环境、多租户 |

### 2.3 与现有架构的关系

- ✅ 复用 `SandboxBackend` 抽象接口
- ✅ 复用 `SandboxManager` 生命周期管理
- ✅ 复用配置 schema 扩展机制
- ✅ 作为可插拔后端，不影响现有 SRT 功能

---

## 3. 配置设计

### 3.1 配置结构

```json
{
  "sandbox": {
    "enabled": true,
    "backend": "opensandbox",
    "mode": "per-session",
    "opensandbox": {
      "mode": "local",  // "local" 或 "vke"
      
      // Local 模式配置
      "local": {
        "serverUrl": "http://localhost:8080",
        "apiKey": "",
        "defaultImage": "opensandbox/code-interpreter:v1.0.1"
      },
      
      // VKE 模式配置
      "vke": {
        "serverUrl": "http://opensandbox-server.vikingbot.svc.cluster.local:8080",
        "apiKey": "",
        "defaultImage": "opensandbox/code-interpreter:v1.0.1",
        "namespace": "vikingbot",
        "kubeconfigPath": "~/.kube/config",
        "tos": {
          "enabled": true,
          "mountPath": "/tos",
          "pvcName": "vikingbot-tos-pvc"
        }
      },
      
      // 通用配置
      "network": {
        "allowedDomains": [],
        "deniedDomains": []
      },
      "runtime": {
        "timeout": 300,
        "cpu": "500m",
        "memory": "1Gi"
      }
    }
  }
}
```

### 3.2 配置 Schema (Pydantic)

在 `vikingbot/config/schema.py` 中新增：

```python
class OpenSandboxLocalConfig(BaseModel):
    """OpenSandbox 本地模式配置."""
    server_url: str = "http://localhost:8080"
    api_key: str = ""
    default_image: str = "opensandbox/code-interpreter:v1.0.1"


class OpenSandboxTOSConfig(BaseModel):
    """OpenSandbox TOS 挂载配置."""
    enabled: bool = True
    mount_path: str = "/tos"
    pvc_name: str = "vikingbot-tos-pvc"


class OpenSandboxVKEConfig(BaseModel):
    """OpenSandbox VKE 模式配置."""
    server_url: str = "http://opensandbox-server.vikingbot.svc.cluster.local:8080"
    api_key: str = ""
    default_image: str = "opensandbox/code-interpreter:v1.0.1"
    namespace: str = "vikingbot"
    kubeconfig_path: str = "~/.kube/config"
    tos: OpenSandboxTOSConfig = Field(default_factory=OpenSandboxTOSConfig)


class OpenSandboxNetworkConfig(BaseModel):
    """OpenSandbox 网络配置."""
    allowed_domains: list[str] = Field(default_factory=list)
    denied_domains: list[str] = Field(default_factory=list)


class OpenSandboxRuntimeConfig(BaseModel):
    """OpenSandbox 运行时配置."""
    timeout: int = 300
    cpu: str = "500m"
    memory: str = "1Gi"


class OpenSandboxBackendConfig(BaseModel):
    """OpenSandbox 后端配置."""
    mode: Literal["local", "vke"] = "local"
    local: OpenSandboxLocalConfig = Field(default_factory=OpenSandboxLocalConfig)
    vke: OpenSandboxVKEConfig = Field(default_factory=OpenSandboxVKEConfig)
    network: OpenSandboxNetworkConfig = Field(default_factory=OpenSandboxNetworkConfig)
    runtime: OpenSandboxRuntimeConfig = Field(default_factory=OpenSandboxRuntimeConfig)


# 更新 SandboxBackendsConfig
class SandboxBackendsConfig(BaseModel):
    """Sandbox backends configuration."""
    srt: SrtBackendConfig = Field(default_factory=SrtBackendConfig)
    docker: DockerBackendConfig = Field(default_factory=DockerBackendConfig)
    opensandbox: OpenSandboxBackendConfig = Field(default_factory=OpenSandboxBackendConfig)  # 新增
```

---

## 4. 核心组件设计

### 4.1 OpenSandboxBackend (sandbox/backends/opensandbox.py)

```python
"""OpenSandbox backend implementation."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from vikingbot.sandbox.base import SandboxBackend, SandboxNotStartedError
from vikingbot.sandbox.backends import register_backend

if TYPE_CHECKING:
    from vikingbot.config.schema import SandboxConfig


@register_backend("opensandbox")
class OpenSandboxBackend(SandboxBackend):
    """OpenSandbox 沙箱后端实现.
    
    支持两种运行模式:
    - local: 本地 Docker 运行
    - vke: VKE Kubernetes 运行
    """

    def __init__(self, config: "SandboxConfig", session_key: str, workspace: Path):
        self.config = config
        self.session_key = session_key
        self._workspace = workspace
        self._sandbox_id: str | None = None
        self._client: httpx.AsyncClient | None = None
        
        # 获取 OpenSandbox 配置
        self._osb_config = config.backends.opensandbox
        
        # 根据模式选择配置
        if self._osb_config.mode == "local":
            self._server_config = self._osb_config.local
        else:
            self._server_config = self._osb_config.vke

    async def start(self) -> None:
        """启动 OpenSandbox 沙箱实例."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        
        # 初始化 HTTP 客户端
        self._client = httpx.AsyncClient(
            base_url=self._server_config.server_url,
            headers={
                "OPEN-SANDBOX-API-KEY": self._server_config.api_key,
                "Content-Type": "application/json"
            },
            timeout=httpx.Timeout(60.0)
        )
        
        # 创建沙箱
        await self._create_sandbox()

    async def _create_sandbox(self) -> None:
        """调用 OpenSandbox API 创建沙箱."""
        # 构建环境变量
        env = {}
        
        # VKE 模式下配置 TOS 挂载
        if self._osb_config.mode == "vke" and self._osb_config.vke.tos.enabled:
            env["TOS_MOUNT_PATH"] = self._osb_config.vke.tos.mount_path
        
        # 构建创建请求
        create_payload = {
            "image": self._server_config.default_image,
            "entrypoint": ["/opt/opensandbox/code-interpreter.sh"],
            "env": env,
            "timeout": self._osb_config.runtime.timeout,
            "resources": {
                "cpu": self._osb_config.runtime.cpu,
                "memory": self._osb_config.runtime.memory
            },
            "extensions": {}
        }
        
        # VKE 模式添加 TOS Volume 配置
        if self._osb_config.mode == "vke" and self._osb_config.vke.tos.enabled:
            create_payload["extensions"]["volumes"] = [
                {
                    "name": "tos",
                    "persistentVolumeClaim": {
                        "claimName": self._osb_config.vke.tos.pvc_name
                    },
                    "mountPath": self._osb_config.vke.tos.mount_path
                }
            ]
        
        # 调用 OpenSandbox API
        response = await self._client.post(
            "/v1/sandboxes",
            json=create_payload
        )
        response.raise_for_status()
        
        result = response.json()
        self._sandbox_id = result["sandboxId"]
        logger.info(f"OpenSandbox created: {self._sandbox_id}")

    async def execute(self, command: str, timeout: int = 60, **kwargs: Any) -> str:
        """在 OpenSandbox 中执行命令."""
        if not self._sandbox_id or not self._client:
            raise SandboxNotStartedError()
        
        # pwd 特殊处理
        if command.strip() == "pwd":
            if self._osb_config.mode == "vke" and self._osb_config.vke.tos.enabled:
                return self._osb_config.vke.tos.mount_path
            return "/"
        
        # 通过 execd API 执行命令
        # 首先获取沙箱详情，找到 execd 端点
        sandbox_response = await self._client.get(f"/v1/sandboxes/{self._sandbox_id}")
        sandbox_response.raise_for_status()
        sandbox_info = sandbox_response.json()
        
        # 调用 execd API
        exec_payload = {
            "command": command,
            "timeout": timeout * 1000  # 毫秒
        }
        
        # 这里需要获取 execd 的访问地址
        # 简化实现：假设通过 OpenSandbox server 代理
        exec_response = await self._client.post(
            f"/v1/sandboxes/{self._sandbox_id}/exec",
            json=exec_payload,
            timeout=timeout + 10
        )
        exec_response.raise_for_status()
        
        exec_result = exec_response.json()
        
        # 构建输出
        output_parts = []
        stdout = exec_result.get("stdout", "")
        stderr = exec_result.get("stderr", "")
        exit_code = exec_result.get("exitCode", 0)
        
        if stdout:
            output_parts.append(stdout)
        if stderr:
            output_parts.append(f"STDERR:\n{stderr}")
        if exit_code != 0:
            output_parts.append(f"\nExit code: {exit_code}")
        
        result = "\n".join(output_parts) if output_parts else "(no output)"
        
        # 截断过长输出
        max_len = 10000
        if len(result) > max_len:
            result = result[:max_len] + f"\n... (truncated, {len(result) - max_len} more chars)"
        
        return result

    async def stop(self) -> None:
        """停止并清理 OpenSandbox 沙箱."""
        if self._sandbox_id and self._client:
            try:
                await self._client.delete(f"/v1/sandboxes/{self._sandbox_id}")
                logger.info(f"OpenSandbox deleted: {self._sandbox_id}")
            except Exception as e:
                logger.warning(f"Error deleting sandbox: {e}")
        
        if self._client:
            await self._client.aclose()
            self._client = None
        
        self._sandbox_id = None

    def is_running(self) -> bool:
        """检查沙箱是否正在运行."""
        return self._sandbox_id is not None and self._client is not None

    @property
    def workspace(self) -> Path:
        """获取沙箱工作目录."""
        return self._workspace
```

---

## 5. TOS 共享目录集成方案

### 5.1 架构说明

在 VKE 模式下，OpenSandbox 沙箱通过 PVC 挂载 TOS：

```
┌─────────────────────────────────────────────────────────┐
│                     VKE Cluster                           │
│  ┌───────────────────────────────────────────────────┐   │
│  │         vikingbot Namespace                        │   │
│  │                                                      │   │
│  │  ┌──────────────┐      ┌──────────────────────┐  │   │
│  │  │   vikingbot  │      │  OpenSandbox Server  │  │   │
│  │  │   Deployment │      │      Deployment       │  │   │
│  │  └──────┬───────┘      └──────────┬───────────┘  │   │
│  │         │                           │               │   │
│  │         │  creates sandbox         │               │   │
│  │         ├──────────────────────────>               │   │
│  │         │                           │               │   │
│  │         │                           │  creates      │   │
│  │         │                           │  sandbox Pod  │   │
│  │         │                           │               │   │
│  │  ┌──────▼───────┐      ┌──────────▼───────────┐  │   │
│  │  │   Sandbox    │      │     Sandbox Pod      │  │   │
│  │  │   (executor) │      │  (with TOS mount)    │  │   │
│  │  └──────────────┘      └──────────┬───────────┘  │   │
│  │                                     │               │   │
│  │                              ┌──────▼───────┐      │   │
│  │                              │  TOS PVC     │      │   │
│  │                              └──────┬───────┘      │   │
│  └─────────────────────────────────────┼──────────────┘   │
│                                        │                  │
│                              ┌─────────▼─────────┐        │
│                              │   TOS Bucket       │        │
│                              └───────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

### 5.2 本地开发模式下的 TOS 模拟

在 `local` 模式下，通过 bind mount 模拟 TOS：

```python
# 在 _create_sandbox 中
if self._osb_config.mode == "local":
    # 本地模式：将本地 TOS 目录 bind mount 到沙箱
    local_tos_path = Path.home() / ".vikingbot" / "tos"
    local_tos_path.mkdir(parents=True, exist_ok=True)
    
    # 配置沙箱挂载
    # (通过 OpenSandbox 的 volume 扩展)
```

---

## 6. 部署配置

### 6.1 OpenSandbox Server 在 VKE 中的部署

在 `deploy/vke/k8s/` 下新增 `opensandbox-server.yaml`：

```yaml
# OpenSandbox Server 部署
apiVersion: apps/v1
kind: Deployment
metadata:
  name: opensandbox-server
  namespace: vikingbot
spec:
  replicas: 1
  selector:
    matchLabels:
      app: opensandbox-server
  template:
    metadata:
      labels:
        app: opensandbox-server
    spec:
      containers:
      - name: opensandbox-server
        image: opensandbox/server:latest  # 使用官方镜像
        imagePullPolicy: Always
        ports:
        - containerPort: 8080
        env:
        - name: OPEN_SANDBOX_API_KEY
          valueFrom:
            secretKeyRef:
              name: opensandbox-secrets
              key: api-key
        resources:
          requests:
            cpu: "1"
            memory: "2Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
---
apiVersion: v1
kind: Service
metadata:
  name: opensandbox-server
  namespace: vikingbot
spec:
  type: ClusterIP
  selector:
    app: opensandbox-server
  ports:
  - protocol: TCP
    port: 8080
    targetPort: 8080
---
# Secret（需要手动创建）
# kubectl create secret generic opensandbox-secrets -n vikingbot --from-literal=api-key=your-api-key
```

### 6.2 更新 vikingbot Deployment

修改 `deploy/vke/k8s/deployment.yaml`：

```yaml
# 在 vikingbot Deployment 中添加 OpenSandbox 相关配置
containers:
- name: vikingbot
  image: __IMAGE_NAME__
  # ... 其他配置 ...
  env:
  # ... 现有环境变量 ...
  - name: NANOBOT_SANDBOX__BACKEND
    value: "opensandbox"
  - name: NANOBOT_SANDBOX__OPENSANDBOX__MODE
    value: "vke"
  - name: NANOBOT_SANDBOX__OPENSANDBOX__VKE__SERVER_URL
    value: "http://opensandbox-server.vikingbot.svc.cluster.local:8080"
  - name: NANOBOT_SANDBOX__OPENSANDBOX__VKE__API_KEY
    valueFrom:
      secretKeyRef:
        name: opensandbox-secrets
        key: api-key
```

---

## 7. 依赖管理

### 7.1 Python 依赖

在 `pyproject.toml` 中添加：

```toml
[project.dependencies]
# ... 现有依赖 ...
httpx = ">=0.27.0"  # 用于 OpenSandbox API 调用
```

### 7.2 可选依赖组

```toml
[project.optional-dependencies]
opensandbox = [
    "httpx>=0.27.0",
]
```

---

## 8. 测试策略

### 8.1 单元测试

新增 `tests/sandbox/test_opensandbox_backend.py`：

```python
"""Tests for OpenSandbox backend."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from vikingbot.sandbox.backends.opensandbox import OpenSandboxBackend


@pytest.mark.asyncio
async def test_opensandbox_local_start():
    """Test OpenSandbox backend starts in local mode."""
    # ... 测试代码 ...
```

### 8.2 集成测试

在 `tests/sandbox/` 下新增集成测试。

---

## 9. 实现优先级

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | 配置 Schema 扩展 | 添加 OpenSandboxBackendConfig 等 |
| P0 | OpenSandboxBackend 实现 | 核心后端类实现 |
| P0 | Local 模式支持 | 本地 Docker 运行 |
| P1 | VKE 模式支持 | Kubernetes 运行 |
| P1 | TOS 挂载集成 | PVC 挂载支持 |
| P2 | 部署清单 | VKE 部署 YAML |
| P2 | 单元测试 | 测试覆盖 |
| P3 | 文档更新 | README 和配置示例 |

---

## 10. 迁移指南

### 10.1 从 SRT 迁移到 OpenSandbox

1. 安装依赖：
```bash
uv pip install -e ".[opensandbox]"
```

2. 更新配置：
```json
{
  "sandbox": {
    "enabled": true,
    "backend": "opensandbox",
    "opensandbox": {
      "mode": "local"
    }
  }
}
```

3. 启动 OpenSandbox Server（本地模式）：
```bash
# 参考 OpenSandbox 官方文档启动本地 server
opensandbox-server init-config ~/.sandbox.toml --example docker
opensandbox-server
```

---

## 11. 参考资料

- [OpenSandbox GitHub](https://github.com/alibaba/OpenSandbox)
- [OpenSandbox 文档](https://github.com/alibaba/OpenSandbox/blob/main/docs/README_zh.md)
- [vikingbot 沙箱集成规范](./11-sandbox-integration.md)
