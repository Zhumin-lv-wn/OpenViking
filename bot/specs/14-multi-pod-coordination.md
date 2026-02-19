# 多 Pod 部署方案

## 核心结论

**飞书官方 WebSocket 集群模式已经解决了所有问题，我们不需要任何协调逻辑！**

| 飞书官方特性 | 说明 |
|-------------|------|
| 多连接支持 | 同一个 app_id 最多可建立 50 个 WebSocket 连接 |
| 消息推送 | 集群模式，**随机推送到一个连接** |
| 广播支持 | ❌ 不支持广播，同一条消息**只推送到一个连接** |

---

## 方案

### 部署方式
- 所有 Pod 都运行 `vikingbot gateway`
- 所有 Pod 都建立 WebSocket 连接
- 通过 TOS PVC（ReadWriteMany）共享会话数据

### 工作流程
```
飞书消息 → 随机推送到某个 Pod → 该 Pod 处理 → 会话写入 TOS
```

---

## 部署配置

### deployment.yaml
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vikingbot
spec:
  replicas: 3  # 建议 2-3 个实现高可用
  template:
    spec:
      containers:
      - name: vikingbot
        volumeMounts:
        - name: vikingbot-data
          mountPath: /root/.vikingbot
      volumes:
      - name: vikingbot-data
        persistentVolumeClaim:
          claimName: vikingbot-data
```

---

## 优势

✅ 超简单 - 无需协调逻辑  
✅ 零依赖 - 不需要额外组件  
✅ 零配置 - 不需要额外环境变量  
✅ 零代码修改 - 现有代码直接用  
✅ 高可用 - 飞书官方集群模式  
✅ 负载均衡 - 飞书随机推送，天然负载均衡  

---

## FAQ

### Q: 多个 Pod 都建立 WebSocket 连接没问题吗？
A: 没问题，飞书官方支持最多 50 个连接。

### Q: 同一个消息会被多个 Pod 接收吗？
A: 不会，飞书集群模式只推送到随机一个连接。

### Q: 需要修改代码吗？
A: 不需要，直接部署多个 Pod 即可。
