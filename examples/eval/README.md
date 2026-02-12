# RAG Evaluation Tool for OpenViking

Evaluate RAG (Retrieval-Augmented Generation) performance using OpenViking's retrieval capabilities.

## Quick Start

```bash
# 0. Install dependencies
uv sync

# 1. Basic evaluation with documents
uv run rag_eval.py --docs_dir ./docs --question_file ./questions.jsonl

# 2. Evaluate with multiple document directories
uv run rag_eval.py --docs_dir ./docs1 --docs_dir ./docs2 --question_file ./questions.jsonl

# 3. Evaluate with documents and code repositories
uv run rag_eval.py --docs_dir ./docs --code_dir ./src --question_file ./questions.jsonl

# 4. Save evaluation report
uv run rag_eval.py --docs_dir ./docs --question_file ./questions.jsonl --output ./results.json

# 5. Enable RAGAS metrics (requires ragas package)
uv run rag_eval.py --docs_dir ./docs --question_file ./questions.jsonl --ragas
```

## Command Options

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `--docs_dir` | No* | - | Document directory or file path (can specify multiple times) |
| `--code_dir` | No* | - | Code repository path (can specify multiple times) |
| `--question_file` | Yes | - | Path to questions file (JSONL format) |
| `--config` | No | `./ov.conf` | Path to OpenViking config file |
| `--data_path` | No | `./data` | Path to OpenViking data directory |
| `--top_k` | No | 5 | Number of contexts to retrieve per query |
| `--output` | No | - | Path to save evaluation results (JSON format) |
| `--ragas` | No | false | Run RAGAS evaluation (requires ragas package) |

*At least one of `--docs_dir` or `--code_dir` must be specified.

## Question File Format

Questions should be in JSONL format with the following structure:

```json
{"question": "What is OpenViking's core positioning?", "answer": "OpenViking is a context database for AI Agents...", "files": ["README.md", "docs/architecture.md"]}
{"question": "How does tiered context loading work?", "answer": "Tiered loading uses L0/L1/L2 layers...", "files": ["docs/context-layers.md"]}
```

Required fields:
- `question`: The question to evaluate

Optional fields:
- `answer`: Ground truth answer (for RAGAS evaluation)
- `files`: List of reference files

## Evaluation Metrics

### Basic Metrics (always available)
- **Total Questions**: Number of questions evaluated
- **Avg Contexts/Question**: Average number of contexts retrieved
- **Questions with Contexts**: Number of questions that retrieved at least one context
- **Retrieval Success Rate**: Percentage of questions with successful retrieval

### RAGAS Metrics (with `--ragas` flag)
- **faithfulness**: Answer faithfulness to retrieved context
- **answer_relevance**: Relevance of generated answer to question
- **context_precision**: Precision of retrieved contexts
- **context_recall**: Recall of relevant contexts

## Configuration

Edit `ov.conf` to configure:
- Embedding model (for vector search)
- VLM model (for LLM-based evaluation)
- Storage backend (local, S3, etc.)

Example `ov.conf`:
```json
{
  "embedding": {
    "dense": {
      "provider": "volcengine",
      "model": "doubao-embedding-vision-250615",
      "api_key": "your-api-key"
    }
  },
  "vlm": {
    "provider": "volcengine",
    "model": "doubao-seed-1-8-251228",
    "api_key": "your-api-key"
  },
  "storage": {
    "vectordb": {
      "backend": "local",
      "path": "./data"
    }
  }
}
```

## Output Format

When `--output` is specified, results are saved in JSON format:

```json
{
  "total_questions": 20,
  "results": [
    {
      "question": "What is OpenViking?",
      "contexts": [
        {
          "uri": "viking://resources/xxx/Overview.md",
          "content": "OpenViking is a context database...",
          "score": 0.618
        }
      ],
      "context_count": 5,
      "ground_truth": "OpenViking is...",
      "files": ["README.md"]
    }
  ],
  "metrics": {
    "total_questions": 20,
    "avg_contexts_per_question": 5.0,
    "questions_with_contexts": 20,
    "retrieval_success_rate": 1.0
  }
}
```

## Examples

### Evaluate Document Retrieval

```bash
# Add documents and evaluate retrieval quality
uv run rag_eval.py \
  --docs_dir ./documentation \
  --question_file ./test_questions.jsonl \
  --output ./eval_results.json
```

### Evaluate Code Repository

```bash
# Evaluate code retrieval for a repository
uv run rag_eval.py \
  --code_dir ./my-project \
  --question_file ./code_questions.jsonl \
  --top_k 10
```

### Full RAGAS Evaluation

```bash
# Install RAGAS dependencies first
pip install ragas datasets

# Run full evaluation with RAGAS metrics
uv run rag_eval.py \
  --docs_dir ./docs \
  --question_file ./questions.jsonl \
  --ragas \
  --output ./full_eval.json
```

## Files

```
rag_eval.py      # Main evaluation script
pyproject.toml   # Project dependencies
README.md        # This file
ov.conf          # OpenViking configuration (create from example)
data/            # Database storage (created automatically)
```

## Tips

- Use `--top_k` to control retrieval granularity
- Set `--output` to save results for later analysis
- Use `--ragas` for comprehensive RAG quality metrics
- Questions should be representative of real usage scenarios
- Ground truth answers improve RAGAS evaluation quality

## Troubleshooting

### Configuration Not Found
```
Error: OpenViking configuration file not found
```
Solution: Create `ov.conf` or set `OPENVIKING_CONFIG_FILE` environment variable

### No Contexts Retrieved
```
Retrieval Success Rate: 0.0%
```
Solution: Check that documents are being added correctly, verify embedding model configuration

### RAGAS Not Available
```
Error: RAGAS not installed
```
Solution: Install with `pip install ragas datasets` or `uv pip install ragas datasets`
