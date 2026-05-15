# P4 Agent Sandbox Architecture

## Orchestrator
Orchestrator 负责接收用户输入、生成执行计划、调用工具、验证执行结果并生成最终回答。

## SafeToolExecutor
SafeToolExecutor 是唯一工具执行入口，负责权限控制、参数校验、审计记录和工具调用。

## Tool Registry
Tool Registry 负责统一注册所有工具，并为系统提供可发现的工具清单。

## Audit
Audit 用于记录任务生命周期、执行计划、工具调用和错误信息。

## TaskStore
TaskStore 用于持久化任务状态、文件信息和运行记录。

## RAG Pipeline
RAG Pipeline 负责执行语义检索、上下文构建、LLM 调用和答案生成。
