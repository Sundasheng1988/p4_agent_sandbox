# P4 Agent Sandbox

## 1. 项目目标

P4 Agent Sandbox 是一个本地 Agent Runtime Prototype。

目标是构建：
* Workflow Runtime
* Knowledge Runtime
* Skill Runtime
* Artifact Runtime

当前重点能力：

* RAG（Retrieval-Augmented Generation）
* Workflow Runtime
* Financial Analysis Skill
* Evidence-based Verification
* Markdown Artifact Generation

---

# 2. 当前系统架构

```text
User Input
↓
FastAPI API
↓
Task Router
↓
Workflow Runtime
↓
Tools / Skills / RAG Pipeline
↓
Verifier
↓
Artifact Generator
```

---

# 3. 当前核心组件

## Runtime

```text
- FastAPI
- Orchestrator
- Workflow Runtime
- Tool Registry
- SafeToolExecutor
- Audit Trace
```

## Knowledge Runtime

```text
- File Upload
- PDF Parsing
- Markdown Parsing
- Chunking
- Embedding
- Hybrid Retrieval
- Context Builder
```

## Financial Skill

```text
- Financial PDF Parsing
- Table Extraction
- Structured Financial Metrics
- RAG-based Analysis
- Evidence Verification
- Markdown Report Generation
```

---

# 4. 启动服务

```bash
pkill -f uvicorn

uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload
```

---

# 5. 清理 Chunk / Embedding

## 删除 Chunk

```bash
rm -f artifacts/chunks/*.chunks.json
rm -f artifacts/chunk_index.json
```

## 删除 Embedding

```bash
rm -f artifacts/vector_manifests/*.vectors.json
rm -f artifacts/vectors/*.npy
rm -f artifacts/vector_index.json
```

---

# 6. 构建知识库

## 构建 Index

```bash
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"构建知识索引","debug":true}' \
| python -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))"
```

---

## 构建 Chunk

```bash
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"构建文本块","debug":true}' \
| python -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))"
```

---

## 构建 Embedding

```bash
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"构建知识向量","debug":true}' \
| python -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))"
```

---

# 7. 财报分析 Workflow

## 财报分析

```bash
curl -sS -X POST http://127.0.0.1:8000/agent/run \
-H "Content-Type: application/json" \
-d '{"user_input":"分析思源电气2025年报","debug":true}' \
| python -c '
import sys,json
d=json.load(sys.stdin)
r=d.get("result",{})
print("ok:", r.get("ok"))
print("error:", r.get("error"))
print("artifact:", r.get("artifact"))
print((r.get("final_output") or "")[:5000])
'
```

---

## 输出完整财报结果

```bash
curl -sS -X POST http://127.0.0.1:8000/agent/run \
-H "Content-Type: application/json" \
-d '{"user_input":"分析思源电气2025年报","debug":true}' \
| python -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))"
```

---

# 8. 调试 / 测试命令

## 查看 Financial RAG Analysis

```bash
curl -sS -X POST http://127.0.0.1:8000/agent/run \
-H "Content-Type: application/json" \
-d '{"user_input":"分析思源电气2025年报","debug":true}' \
| python -c '
import sys,json
d=json.load(sys.stdin)
rag=d.get("result",{}).get("state",{}).get("financial_rag_analysis",{})
analysis=rag.get("analysis",{})

print("has_valid_answer:", rag.get("has_valid_answer"))

for k,v in analysis.items():
    print("\\n==", k, "==")
    print("retrieval_query:", v.get("retrieval_query"))
    print("domains:", v.get("domains"))
    print("retrieval_mode:", v.get("retrieval_mode"))
    print("hits_count:", v.get("hits_count"))
    print("answer:", (v.get("answer") or "")[:300])
'
```

---

## 查看 Retrieval Hits

```bash
curl -sS -X POST http://127.0.0.1:8000/agent/run \
-H "Content-Type: application/json" \
-d '{"user_input":"分析思源电气2025年报","debug":true}' \
| python -c '
import sys,json
d=json.load(sys.stdin)
analysis=d.get("result",{}).get("state",{}).get("financial_rag_analysis",{}).get("analysis",{})

for k,v in analysis.items():
    print("\\n================", k, "================")
    for h in v.get("hits",[])[:3]:
        print("-", h.get("chunk_id"), "score=", h.get("score"))
        print((h.get("snippet") or "")[:300].replace("\\n"," "))
'
```

---

# 9. Financial Parsed 调试

## 生成 financial_parsed

```bash
curl -sS -X POST http://127.0.0.1:8000/agent/run \
-H "Content-Type: application/json" \
-d '{"user_input":"分析思源电气2025年报","debug":true}' \
| python -c '
import sys,json
d=json.load(sys.stdin)
p=d.get("result",{}).get("state",{}).get("parse_financial_pdf",{})
print(json.dumps(p,indent=2,ensure_ascii=False))
'
```

---

## 重建 Chunk / Embedding

```bash
rm -f artifacts/chunks/*.chunks.json
rm -f artifacts/chunk_index.json

rm -f artifacts/vector_manifests/*.vectors.json
rm -f artifacts/vectors/*.npy
rm -f artifacts/vector_index.json
```

```bash
curl -sS -X POST http://127.0.0.1:8000/task/run \
-H "Content-Type: application/json" \
-d '{"user_input":"构建文本块","debug":true}' \
| python -m json.tool
```

```bash
curl -sS -X POST http://127.0.0.1:8000/task/run \
-H "Content-Type: application/json" \
-d '{"user_input":"构建知识向量","debug":true}' \
| python -m json.tool
```

---

## 检查 Chunk 结构

```bash
python - <<'PY'
import json
from pathlib import Path

file_id="902fa7e8363c459d"

p=Path("artifacts/chunks") / f"{file_id}.chunks.json"

data=json.loads(p.read_text(encoding="utf-8"))

print("text_source:", data.get("text_source"))
print("chunk_count:", data.get("chunk_count"))
print("source_chars:", data.get("source_chars"))
print("document_structure_count:", data.get("document_structure_count"))

for t in ["financial_report", "financial_statement_note"]:
    print("\n==", t, "==")
    n=0

    for c in data.get("chunks", []):

        if c.get("section_type") == t:

            print(
                c.get("chunk_id"),
                c.get("financial_topic"),
                c.get("section_title")
            )

            print(
                (c.get("text") or "")[:180].replace("\n"," ")
            )

            n += 1

            if n >= 5:
                break
PY
```

---

# 10. Artifact 输出目录

```text
artifacts/deliverables/
```

例如：

```text
financial_report_20260515_xxx.md
```

---

# 11. 当前已知问题

```text
- think tag 尚未统一清洗
- retrieval routing 仍需优化
- table chunk 权重偏高
- financial_report_path 尚未统一
```

---

# 12. 当前已完成阶段

```text
M1 Runtime Foundation          ✅
M2 Knowledge Runtime           ✅
M2.5 Semantic Retrieval        ✅
M3 RAG Runtime                 ✅
M4 Workflow Runtime            ✅
Financial Analysis Skill v1    ✅
```

---

# 13. 下一阶段

```text
- Query Understanding v2
- Retrieval Routing
- Multi-agent Runtime
- Memory Runtime
- Planning Runtime
```
