# P4 Agent Sandbox
# M0 → M1 Runtime Foundation 里程碑总结

---

## 1. 项目愿景

构建一个本地可控、可扩展的 Agent Runtime 平台，具备：

- 可控工具调用（Tool Registry）
- 明确权限边界（Policy）
- 全链路可审计（Audit）
- 任务持久化（TaskStore / SQLite）
- 文件沙盒机制（sandbox_root）
- 状态机驱动执行（Plan → Execute → Verify → Report）

目标不是写脚本，而是构建一个 Agent 操作系统核心。

---

## 2. 当前系统架构
User Input
↓
Orchestrator (rule-based planner)
↓
SafeToolExecutor
├─ Policy
├─ Args Schema 校验
├─ Tool Registry
└─ Audit
↓
Tool Handler
↓
TaskStore + Audit
↓
Report

---

## 3. 核心模块说明

| 模块 | 职责 |
|------|------|
| Orchestrator | 将自然语言映射为 ToolCall |
| SafeToolExecutor | 统一工具入口（权限 + 校验 + 执行） |
| Policy | 控制允许调用的工具 |
| TaskStore | 任务状态持久化 |
| AuditLogger | 记录系统操作日志 |
| ToolRegistry | 工具注册与加载 |

---

# M1：文件工具能力建立

---

## 4. 文件系统双视图设计

### ① files_list（逻辑视图 / SQLite）

用途：列出已上传文件（数据库索引）

返回字段：

- file_id
- filename
- mime
- ext
- size
- sha256
- rel_dir
- raw_name
- created_at

启动命令：
```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

测试命令：
```bash
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"列出已上传文件"}' \
| python -m json.tool

### ② file_list（物理视图 / Filesystem）

用途：列出 sandbox_root 下目录内容

返回字段：

name

is_dir

size

mtime

测试命令：
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"列出 uploads 目录"}' \
| python -m json.tool

## 5. 安全机制（Sandbox）

所有路径必须在 sandbox_root 内

resolve() + is_relative_to() 防止路径逃逸

Policy 控制允许的工具

args_schema 严格校验参数
非法路径应返回：
path must be under sandbox

## 6. 已实现能力清单

✔ Tool Registry 动态加载
✔ Policy 生效
✔ Audit 可记录
✔ TaskStore 状态流转正常
✔ file_list 与 files_list 功能清晰区分
✔ file_read_by_id 可读取文件
✔ file_parse_by_id 可解析文本
✔ FastAPI + Uvicorn 正常运行

## 7. 当前局限

final_answer 仍为 Python repr 风格

Orchestrator 仍为 rule-based（未接入 LLM）

相对路径尚未自动归一化

未实现文件摘要 / 批量解析 / 搜索能力

## 8. 设计决策记录
决策 1：阶段性使用绝对路径

原因：

避免 sandbox 校验冲突

快速验证能力闭环

未来改进：

在 SafeToolExecutor 内统一做路径归一化

决策 2：严格 args_schema 校验

禁止 unknown args

避免工具“假成功”

提升系统可控性

## 9. 下一阶段规划
M2 目标候选

文件摘要能力

批量解析

内容搜索

向量索引

LLM 参与规划

里程碑状态

阶段：M1 - File Tools Foundation
状态：✅ 已完成
系统已具备 Agent Runtime 雏形。

## 10. 知识库重置与环境清理

当知识库出现以下情况时，可执行一次完整重置：

SQLite 中存在脏数据
uploads/ 与 db/app.db 记录不一致
artifacts/ 中的索引、chunk、向量结果需要整体重建
调整 chunk 策略或 embedding 逻辑后，需要从干净状态重新构建

### 10.1 删除数据库与索引产物
rm -f db/app.db
rm -f artifacts/knowledge_index.json
rm -f artifacts/chunk_index.json
rm -f artifacts/vector_index.json
rm -f artifacts/knowledge/*.summary.json
rm -f artifacts/chunks/*.chunks.json
rm -f artifacts/vector_manifests/*.vectors.json
rm -f artifacts/vectors/*.npy

### 10.2 清空上传文件目录

先检查当前 uploads/ 目录内容：

ls -lh ./uploads

清空全部上传文件：

rm -rf ./uploads/*

确认目录已清空：

find ./uploads -type f

### 10.3 清空运行日志
rm -f ./logs/*.jsonl

### 10.4 重置后的系统状态

执行完上述命令后，系统会进入“空库状态”：

db/app.db 已删除
artifacts/ 下的知识索引、chunk、向量产物已删除
uploads/ 已清空
logs/ 已清空

此时需要重新执行以下流程：

重启服务
重新上传测试文档
重新执行：
构建知识索引
构建文本块
构建知识向量

10.5 重建知识库标准流程

### 上传指令
curl -sS -X POST http://127.0.0.1:8000/files/upload \
  -F "file=@/home/sundasheng/p4_agent_sandbox/docs/test_kb/agent_glossary.md"

curl -sS -X POST http://127.0.0.1:8000/files/upload \
  -F "file=@/home/sundasheng/p4_agent_sandbox/docs/test_kb/architecture.md"

curl -sS -X POST http://127.0.0.1:8000/files/upload \
  -F "file=@/home/sundasheng/p4_agent_sandbox/docs/test_kb/ops_playbook.md"

curl -sS -X POST http://127.0.0.1:8000/files/upload \
  -F "file=@/home/sundasheng/p4_agent_sandbox/docs/test_kb/roadmap.md"

🚀 上传后立刻验证（非常关键）
curl -sS http://127.0.0.1:8000/files | python -m json.tool

上传文件后，按顺序执行：

1️⃣ 建 index
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"构建知识索引","debug":true}' \
| python -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))"

2️⃣ 建 chunk（你刚优化的关键步骤）
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"构建文本块","debug":true}' \
| python -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))"

3️⃣ 建 embedding
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"构建知识向量","debug":true}' \
| python -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))"
10.6 注意事项
删除 db/app.db 后，原有文件记录与任务记录都会丢失
删除 uploads/* 后，需要重新上传所有文档
删除 artifacts/* 后，需要重新构建知识索引、chunk 和向量
当修改 chunk 策略、embedding 输入文本或检索逻辑时，建议执行一次完整重置