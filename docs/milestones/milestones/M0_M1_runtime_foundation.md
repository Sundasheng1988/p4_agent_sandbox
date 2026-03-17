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

5. 安全机制（Sandbox）

所有路径必须在 sandbox_root 内

resolve() + is_relative_to() 防止路径逃逸

Policy 控制允许的工具

args_schema 严格校验参数
非法路径应返回：
path must be under sandbox

6. 已实现能力清单

✔ Tool Registry 动态加载
✔ Policy 生效
✔ Audit 可记录
✔ TaskStore 状态流转正常
✔ file_list 与 files_list 功能清晰区分
✔ file_read_by_id 可读取文件
✔ file_parse_by_id 可解析文本
✔ FastAPI + Uvicorn 正常运行

7. 当前局限

final_answer 仍为 Python repr 风格

Orchestrator 仍为 rule-based（未接入 LLM）

相对路径尚未自动归一化

未实现文件摘要 / 批量解析 / 搜索能力

8. 设计决策记录
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

9. 下一阶段规划
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