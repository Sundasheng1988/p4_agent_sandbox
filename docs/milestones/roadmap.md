# Agent Sandbox Roadmap

## 🎯 Current Focus（当前开发主线）

- M4.3.1 Multi-format Knowledge Input（PDF / DOCX 接入）
- M4.5.4 Structure-aware Context（结构化上下文）

> 当前策略：优先扩展知识输入能力，同时增强 Context 结构能力

## M1 Runtime Foundation （已完成 ✅）
- FastAPI API
- Orchestrator
- SafeToolExecutor
- Tool Registry
- TaskStore
- Audit
- Sandbox
- File Tools

## M2 Knowledge System （已完成 ✅）
- File Parsing 
- Structured Chunking（Markdown-aware）
- Knowledge Index
- Incremental Build
- Full Text Search（chunk-level）

## M2.5 Semantic Retrieval Runtime （已完成 ✅）
- Chunking
- Embedding
- Vector Index
- Semantic Search

## M3 RAG Runtime （已完成 ✅）
- Retrieval
- Context Assembly
- LLM Reasoning
- Answer Generation
- Source Attribution
- Debug / User Mode


## M4.1 LLM Planner （已完成 ✅）
- LLM-based plan generation (JSON)
- Tool schema validation
- Robust JSON parsing
- Rule-based fallback


### M4.2 Multi-step Tool Use （已完成 ✅）
- Sequential tool execution
- Step result passing
- Execution loop
- Context injection across steps

### M4.3 Reflection / Verification （已完成 ✅）
- Result self-check
- Detect empty / weak / insufficient outputs
- Retry / re-plan when needed
- Improve answer reliability

让系统具备这 4 个能力：
→ 执行完成
→ 检查结果质量
→ 判断是否不足
→ 触发 retry / re-plan / fallback

---

## M4.3+ Retrieval & RAG Enhancement（✅）

> 在不改变 M1–M4.3 架构前提下，对 Retrieval 和 RAG 进行能力升级

### 1. Hybrid Retrieval（已完成 ✅）
- Keyword Retrieval（chunk-level full text）
- Semantic Retrieval（embedding）
- Fusion（RRF）

### 2. Chunk-level Full Context（已完成 ✅）
- chunk_id → full_text 回表
- snippet / full_text 分离
- 避免截断信息导致回答失败

### 3. Metadata-aware Retrieval（已完成 ✅）
- domain / file_type / source 过滤
- Retrieval scope 控制

### 4. Retrieval Pipeline Integration（已完成 ✅）
- Hybrid Retrieval 接入 RAG pipeline
- 替换原 semantic-only retrieval


### M4.4 Hybrid Planner（LLM + Rule）【Deferred】
- Dynamic tool selection
- Tool-aware prompting
- Rule-first for deterministic tasks
- LLM-first for semantic / ambiguous tasks
- Reduce hardcoded routing
- Planner stability optimization
> 当前优先级下调，待工具体系更丰富后再推进

## M4.5 Context Builder（当前阶段重点）

> 当前系统瓶颈，决定复杂问题能力上限  
> 已从“TopK 拼接”逐步演进为“上下文决策系统”

---

### M4.5.1 Basic Context Assembly（已完成✅）
- Top-K chunk 拼接
- 基础上下文构建
- full_text 回表支持

---

### M4.5.2 Query-aware Context（已完成 ✅）
- 基于 query 类型的排序（process / architecture / compare / relation）
- Section-aware prioritization（architecture / step / node）
- 提升区别题 / 关系题表现

---

### M4.5.3 Context Intelligence（已完成 ✅）
> 当前稳定版本

- Explicit rerank（context_score）
- Noise filtering（failure / error / keywords / improve）
- Context relevance 优化
- Debug 可解释性（context_score / full_context）
- 支持更大 top_k（10+）

---

### M4.5.4 Structure-aware Context（下一阶段 🚧）
> 当前真正要做的重点

- Chunk ordering（按文档顺序恢复）
- Adjacent chunk merge（连续块合并）
- Section grouping（按标题组织）
- Multi-section aggregation（支持对比 / 关系问题）

---

### M4.5.5 Context Optimization（🔮 规划中）
- Token budget control
- Context compression / summarization
- Redundancy removal
- Dynamic context shaping
---

## M4.3++ Multi-format Knowledge Input（当前主线）
当前状态：🚧 进行中

> 扩展知识入口，从 Markdown 扩展到真实世界文档

- PDF parsing
- DOCX parsing
- Unified document schema
- Pipeline integration（parse → chunk → embedding → retrieval → rag）


---

## M4.6 Advanced Verification（Harness 强化）

> 将 Verification 升级为系统级可靠性层

### Capabilities
- Evidence-based validation（基于命中内容判断）
- Partial-answer detection（部分正确识别）
- Confidence scoring（回答质量评估）
- Smarter retry / re-plan 策略
- Failure classification（无结果 / 弱结果 / 错误结果）

## M5 Agent Memory
- Session Memory
- Persistent Memory
- User Preferences
- Task History Reuse

## M6 Online Search & Live Knowledge
- Trusted Web Search
- News Retrieval
- Source Scoring
- Source Filtering
- Live Knowledge Summarization

## M7 Agent UI Workspace
- Agent Chat UI
- Task / Plan Display
- Tool Call Trace
- Source Panel
- Knowledge Base Panel
- Debug / User View Switch

## M8 Domain Agents
- News Agent
- Research Agent
- Knowledge Agent
- Personal Workflow Agent


---

# 🧠 System Architecture Overview

> 当前系统已经从基础 RAG 演进为 Agent Runtime，包含检索、执行、验证闭环
                          ┌────────────────────────────┐
                          │        User Input          │
                          └─────────────┬──────────────┘
                                        │
                                        ▼
                    ┌──────────────────────────────────┐
                    │         Orchestrator             │
                    │   Plan → Execute → Verify Loop   │
                    │         【已完成】               │
                    └─────────────┬────────────────────┘
                                  │
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼

┌────────────────────┐   ┌────────────────────┐   ┌────────────────────┐
│      Planner        │   │   Tool Executor    │   │     Verifier        │
│  LLM + Rule Hybrid  │   │ SafeToolExecutor  │   │ Reflection / Check  │
│   【已完成】         │   │   【已完成】        │   │   【已完成】         │
└─────────┬──────────┘   └─────────┬──────────┘   └─────────┬──────────┘
          │                        │                        │
          │                        ▼                        │
          │           ┌──────────────────────────┐         │
          │           │     Tool: knowledge_rag  │◄────────┘
          │           │        【已完成】         │
          │           └──────────┬───────────────┘
          │                      │
          ▼                      ▼

              ┌──────────────────────────────────┐
              │        RAG Pipeline              │
              │      【已完成（基础）】          │
              └─────────────┬────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                                       ▼

┌────────────────────────┐           ┌────────────────────────┐
│   Keyword Retrieval     │           │   Semantic Retrieval    │
│ (Full-text on chunks)   │           │ (Embedding / Vector)    │
│     【已完成】           │           │     【已完成】           │
└──────────┬─────────────┘           └──────────┬─────────────┘
           │                                     │
           └──────────────┬──────────────────────┘
                          ▼
                 ┌────────────────────┐
                 │    RRF Fusion      │
                 │    【已完成】       │
                 └────────┬───────────┘
                          ▼
                 ┌────────────────────┐
                 │   Top-K Chunks     │
                 └────────┬───────────┘
                          ▼
                 ┌────────────────────────────┐
                 │ Context Builder（Advanced）│
                 │ Rerank + Filtering + Query-aware
                 │【已完成（M4.5.3）】           │
                 └────────┬───────────────────┘
                          ▼
                 ┌────────────────────┐
                 │        LLM         │
                 │ qwen2.5:7b         │
                 │   【已完成】        │
                 └────────────────────┘


────────────────────────────────────────────────────────────
🔧 Retrieval Enhancement（M4.3+ 已完成能力）
────────────────────────────────────────────────────────────

┌────────────────────────────────────────────┐
│ Hybrid Retrieval Pipeline                  │
│ - Keyword + Semantic + RRF                │
│ - chunk-level full text retrieval         │
│ - metadata filtering (domain / source)    │
│ - full_text enrichment                    │
│              【已完成】                    │
└────────────────────────────────────────────┘


────────────────────────────────────────────────────────────
🚧 当前瓶颈（进行中）
────────────────────────────────────────────────────────────

┌────────────────────────────────────────────┐
│ Advanced Context Builder                  │
│ - chunk ordering                          │
│ - adjacent chunk merge                    │
│ - section grouping                        │
│ - multi-section reasoning support         │
│              【进行中】                    │
└────────────────────────────────────────────┘


────────────────────────────────────────────────────────────
🔮 Future Architecture（规划中）
────────────────────────────────────────────────────────────

┌────────────────────────────────────────────┐
│ Advanced Verification / Harness            │
│ - answer quality scoring                  │
│ - partial answer detection                │
│ - smarter retry / re-plan                 │
│              【规划中】                    │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ Agent Memory                              │
│ - session memory                          │
│ - persistent memory                       │
│ - user preference                         │
│              【规划中】                    │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ Online Knowledge                          │
│ - web search                              │
│ - live knowledge retrieval                │
│              【规划中】                    │
└────────────────────────────────────────────┘
