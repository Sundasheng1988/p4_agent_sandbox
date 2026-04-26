# Dev Log

## 2026-03-13
完成 knowledge chunking，生成 chunk_index.json。

## 2026-03-14
接入 all-MiniLM-L6-v2，本地测试 embedding 模型加载。

## 2026-03-15
完成 M2.5.2 Semantic Runtime：

- knowledge_build_embeddings
- knowledge_semantic_search
- 向量存储结构：
  - vectors/
  - vector_manifests/
  - vector_index.json

语义搜索链路：

User Query  
↓  
Embedding  
↓  
Vector Similarity Search  
↓  
Top-K Chunks

---

## 2026-03-15 (M3 RAG Runtime)

开始 M3 开发。

M3 的目标只有一句话：

**让系统能够用知识库回答问题。**

RAG（Retrieval Augmented Generation）流程：
User Question
↓
Semantic Retrieval
↓
Chunk Selection
↓
Context Assembly
↓
LLM (Qwen / Ollama)
↓
Answer

---

### 新增能力

实现 RAG Tool：
knowledge_rag_answer

功能：

1️⃣ 语义检索 Top-K chunk  
2️⃣ 从 artifacts/chunks/*.chunks.json 读取完整 chunk 原文  
3️⃣ 构建 full_context  
4️⃣ 构建 LLM Prompt  
5️⃣ 调用本地 Ollama Qwen2.5-7B-Instruct  
6️⃣ 返回 Answer

---

### Full Context RAG

升级 Context 构建逻辑：
Vector Hit
↓
chunk_id
↓
chunks.json
↓
Full Chunk Text

避免只使用 snippet。

上下文结构：

[file]
chunk_id
score
chunk_text

---

### Prompt Design

System Prompt：

- 强制中文回答
- 避免 hallucination
- 必须依据 context
- context 不足时返回：
未在知识库中找到明确答案


---

### 输出结构优化

RAG 输出：


问题
回答
来源

示例：


问题：rabbit 是什么

回答：
兔子。在故事中，兔子多次出现，如拿出怀表查看时间。

来源：

alice.txt / chunk_id / score


---

### Debug / User 双模式

新增 API 参数：


debug: true | false


debug=true（开发模式）

返回：

- plan
- step_results
- hits
- full_context
- prompt_preview

debug=false（用户模式）

只返回：


trace_id
user_input
final_answer
status


---

### 当前系统能力

系统已具备完整知识问答链路：


User Question
↓
Orchestrator
↓
knowledge_rag_answer
↓
Semantic Retrieval
↓
Context Assembly
↓
Ollama / Qwen
↓
Answer


---

### 当前 Milestone 状态


M1 Runtime Foundation ✅
M2 Knowledge Runtime ✅
M2.5 Semantic Runtime ✅
M3 RAG Runtime ✅ (基本完成)

---

# 2026-03-16

完成 M3 RAG Runtime

功能：
- 文档上传
- 知识索引构建
- 文本 chunking
- embedding 生成
- vector retrieval
- context builder
- LLM 问答
- 来源引用
- debug/user 模式

验证：
terminology.md 成功问答
语义同义问题测试成功
知识库外问题无 hallucination

# 2026-03-22
### 新增能力：Lightweight Rerank（检索重排序）

在原有 semantic search 基础上，引入 **规则增强排序层（rerank）**：

原始流程：

Query  
↓  
Embedding  
↓  
Cosine Similarity  
↓  
Top-K  

升级为：

Query  
↓  
Embedding  
↓  
Cosine Similarity（base_score）  
↓  
Rerank（规则加权）  
↓  
Final Ranking  

---

### Rerank 核心机制

定义：


final_score = base_score + rerank_bonus


新增字段：

- score（原始向量分数）
- rerank_bonus（规则加权）
- rerank_score（最终排序分）

---

### Rerank 规则设计

1️⃣ 标题完全命中（强权重）

- query == section_title  
- query ⊂ section_title  

👉 提升 Top1 命中率  

---

2️⃣ 标题关键词命中

- query terms 命中 section_title  
👉 提升语义对齐能力  

---

3️⃣ 正文关键词命中

- 命中 snippet / chunk_text  
👉 弱增强  

---

4️⃣ 文档类型加权（Playbook）

- ops_playbook.md 等操作文档  
👉 更适合问答  

---

5️⃣ 噪声块抑制

- 纯标题空块降权  
👉 减少无效 chunk  

---

### 效果验证

Case 1：

query：如何重建知识库  

结果：

- 正确 chunk 提升至 Top1  
- rerank_score ≫ base_score  

---

Case 2：

query：如何清空知识库运行数据  

结果：

- 目标 chunk（清空操作）提升至 Top1  
- rerank_bonus ≈ 0.4  
- 成功压制“语义相似但意图不符”的 chunk  

---

### 系统能力提升

从：

👉 语义检索（Semantic Similarity）

升级为：

👉 **语义 + 结构 + 规则 的混合检索（Hybrid Retrieval v1）**

---

### 当前系统阶段评估

M2.5 → **增强版 Semantic Retrieval**  
M3 → **可用级 RAG Runtime（稳定 Top1 命中）**

系统已具备：

- 高质量 chunk 命中  
- 可控排序机制  
- 可解释检索结果（score / bonus）  

---

# 2026-03-23

## 🧱 M3 收尾固化（Stabilization）

在完成 RAG 主链路（Chunk → Embedding → Retrieval → Rerank → QA）后，对系统进行一次收尾优化，目标是：

👉 降噪  
👉 收敛  
👉 稳定排序  

本次不新增功能，属于工程质量提升。

---

## ✅ A. 过滤纯标题空块（Chunk 清洗）

### 问题

存在无效 chunk：

- 仅包含标题（如：Ops Playbook）
- 无正文内容
- embedding 无信息量
- 干扰 Top-K 排序

---

### 处理策略

过滤条件：

- `heading_level == 1`
- `title ≈ snippet`
- `文本长度 ≤ 40`

---

### 效果

- 移除无效 chunk
- 提升检索质量
- 减少 rerank 依赖

---

## ✅ B. Rerank 权重收敛（排序稳定化）

### 问题

rerank_bonus 过大（≈0.4+），导致：

- 规则压制 embedding
- 排序不稳定

---

### 调整方案

| 规则 | 调整前 | 调整后 |
|------|--------|--------|
| 标题完全命中 | 0.20 | 0.16 |
| 标题关键词上限 | 0.16 | 0.12 |
| snippet 命中上限 | 0.06 | 0.04 |

---

### 新增机制（关键）

```python
bonus = min(bonus, 0.28)
效果
embedding 主导排序
rerank 作为微调
排序更平滑稳定
🧪 验证结果
Case：如何清空知识库运行数据
正确 chunk 稳定 Top1
rerank_bonus = 0.28（受控）
成功压制语义相似但不相关内容
噪声块表现
Chunk / Runtime / RAG / Orchestrator
→ rerank_bonus ≈ -0.03

👉 泛概念节点被有效压制

📊 当前系统状态
Chunk：✅ 已清洗
Embedding：✅ 稳定
Retrieval：✅ cosine
Rerank：✅ 收敛完成
RAG：✅ 可用
🏁 阶段结论

👉 M3 已完成（可交付级 RAG 系统）

具备：

稳定 Top1 命中
可解释排序（score / bonus）
可控噪声

## 📅 2026-03-24
### 🎯 阶段：M3 RAG Runtime 收尾固化完成

---

## 🧩 本日核心工作

本日目标为对 M3（RAG Runtime）进行收尾与工程固化，确保系统具备：

- 可用性
- 稳定性
- 可恢复能力（reset）
- 可持续演进能力（进入 M4 前提）

---

## ✅ 1. Chunk 结构优化（已完成）

### 优化内容
- 引入结构化 Markdown chunk（section_title）
- 按语义分块，而非纯长度切分
- 提高检索精度（title-level recall）

### 新能力
- chunk 具备：
  - `chunk_id`
  - `section_title`
  - `content`

---

## ✅ 2. 噪声块过滤（纯标题块）

### 问题
存在如下无效 chunk：

```text
Ops Playbook
（无正文）
解决

在 chunking 阶段增加过滤逻辑：

若：
content 为空
或仅包含标题
→ 直接丢弃
收益
提升 embedding 质量
避免语义污染
提高 RAG 命中率
✅ 3. Rerank 权重收敛（稳定性优化）
调整内容
项目	原值	调整后
标题完全命中	0.20	0.16
标题关键词累计上限	0.16	0.12
snippet 命中上限	0.06	0.04
目标
防止 rerank 过拟合
降低标题 bias
提升整体排序稳定性
✅ 4. knowledge_reset 工具（关键能力）
功能

新增运维工具：

knowledge_reset

支持：

项目	默认
reset_db	✅
reset_artifacts	✅
reset_logs	❌
reset_uploads	❌
能力说明
1. 数据库重置
删除 db/app.db
自动重建表结构
2. 知识运行数据清理

清空：

artifacts/knowledge
artifacts/chunks
artifacts/vectors
artifacts/vector_manifests
各类 index.json
3. 保留原始数据（Soft Reset）
uploads 不删除
logs 不删除
验证结果（已通过）
✔ artifacts 清空
find artifacts -type f
# → 空
✔ DB 清空
SELECT COUNT(*) FROM files → 0
SELECT COUNT(*) FROM tasks → 0
✔ RAG 失效（符合预期）
error: vector_index.json not found
hits: []
✔ uploads 保留
ls uploads
# → 存在
结论

knowledge_reset 已达到工程级可靠性，可作为运行时维护工具使用

✅ 5. Git 提交（M3 收官）
提交记录
feat(M3): finalize RAG stabilization
feat(M3): add knowledge_reset tool and verify runtime cleanup flow
本次变更包含
chunking 重构
rerank 优化
semantic search 稳定性增强
RAG pipeline 优化
knowledge_reset 工具
test_kb 测试集
文档更新（dev_log / roadmap）


# 2026-03-29

## M4.1 Agent Intelligence：LLM Planner v1 打通

今天完成了 M4.1 的第一阶段：  
将 **LLM Planner** 正式接入 Orchestrator，使系统从纯 rule-based 规划升级为：

User Input  
↓  
LLM Planner  
↓  
Tool Plan  
↓  
SafeToolExecutor  
↓  
Tool Result  
↓  
Fallback（如有需要）

---

### 新增能力

实现内容：

- 在 `config.yaml` 中加入 `planner` 配置
- 在 `config.py` 中补充 `PlannerConfig`
- 在 `orchestrator.py` 中加入：
  - `plan_rule_based()`
  - `plan()`（LLM 优先，失败时 fallback）
- 新增 `app/core/planner.py`
- 接入本地 Ollama / Qwen 作为 Planner 模型
- 支持 planner 审计事件：
  - `planner_llm`
  - `planner_fallback`

---

### Planner 机制

当前模式：

- `planner.mode = "llm"`：优先使用 LLM Planner
- 若 LLM 输出为空、JSON 非法、或抛异常：
  - 自动 fallback 到 `plan_rule_based()`

当前限制：

- 仅允许 **0 或 1 个 step**
- 输出必须为 JSON 数组
- 每个 step 格式：
  - `{"name": "...", "args": {...}}`

---

### Prompt 调优

针对早期误判问题，重写 Planner Prompt，重点强化了三类工具边界：

1. **构建类工具**
   - `knowledge_build_index`
   - `knowledge_build_chunks`
   - `knowledge_build_embeddings`

2. **搜索类工具**
   - `knowledge_search`
   - `knowledge_semantic_search`

3. **问答类工具**
   - `knowledge_rag_answer`

同时明确要求：

- “找、看看、了解、查找、找出来”  
  优先走搜索类工具
- “构建、生成、重建索引/文本块/向量”  
  才走构建类工具
- “什么是、如何、怎么、为什么”  
  优先走问答类工具

---

### Bug 修复

修复了 Planner 执行中的关键异常：

- `local variable 'raw_text' referenced before assignment`

原因：
- `generate_with_ollama()` 异常时，异常分支提前引用了未定义的 `raw_text`

修复方式：
- 将 LLM 调用整体纳入 `try/except`
- 为 `raw_text / parsed_json / llm_out` 提供安全默认值
- 增加空输出保护：
  - `empty planner output`

---

### 验证结果

#### Case 1
输入：

`把和知识库重建有关的信息帮我找出来`

LLM Planner 输出：

```json
[{"name":"knowledge_semantic_search","args":{"query":"知识库重建","limit":10}}]

Case 2

输入：

帮我找一下知识库里关于重建知识库的内容

LLM Planner 输出：

[{"name":"knowledge_semantic_search","args":{"query":"重建知识库","limit":10}}]

结果：

工具选择正确
query 提炼合理
命中 ops_playbook.md / 如何重建知识库
Case 3

输入：

我想了解一下这个知识库系统

LLM Planner 输出：

[{"name":"knowledge_semantic_search","args":{"query":"知识库系统","limit":10}}]

结果：

成功将自然语言“了解一下”映射为搜索类工具
说明 Planner 已具备一定自然语言泛化能力
Case 4

输入：

知识库如果坏了应该怎么恢复

LLM Planner 输出：

[{"name":"knowledge_semantic_search","args":{"query":"知识库坏了怎么恢复","limit":10}}]

结果：

工具选择正确
未误选 reset / build 类工具
搜索意图判断合理

## [M4.2] Multi-step Tool Execution + Context Passing

### 🎯 目标
让 Agent 支持多步计划执行，并允许步骤之间传递上下文数据。

---

### ✅ 已完成能力

#### 1. 多步计划（Planner）
- LLM 可生成多步 ToolCall
- 支持 step id（如 step1 / step2）
- 支持结构化 plan 输出

示例：
```json
[
  {"id": "step1", "name": "knowledge_semantic_search", ...},
  {"id": "step2", "name": "knowledge_rag_answer", ...}
]

#### 2. Execution Loop
顺序执行 plan
每步产出 StepResult
支持失败中断（fail-fast）

#### 3. Step 引用机制（关键能力）

支持：

"extra_context": "$step1.output.hits"

实现：

执行前解析 $stepX.output.xxx
自动替换为真实数据
支持嵌套字段访问

#### 4. RAG 上下文注入升级

新增能力：

step1 的 hits → 注入 step2
拼接到 RAG prompt 中

结构：

知识库上下文:
...

[Planner Extra Context]
<step1 hits>

#### 5. knowledge_rag_answer 扩展

新增参数：

extra_context

新增逻辑：

normalize extra_context → string
注入 run_rag_pipeline
输出 extra_context_used / preview

#### 6. rag_pipeline 扩展

新增能力：

支持 extra_context
自动拼接到 prompt

📅 Dev Log — 2026-03-29
🚧 当前阶段

M4 Agent Intelligence → M4.3 Reflection / Verification（已完成核心流程）

一、今日完成内容
✅ M4.3 核心能力已实现

本阶段目标：

让系统具备执行后的“自检能力”，能够判断结果是否有效，并在必要时触发 retry / re-plan / fallback。

当前已实现：

1. Reflection 机制（执行后自检）
每个 step 执行后进入验证流程
不再仅依赖 tool_result.ok
2. 空结果识别（Insufficient Detection）
knowledge_search 返回 hits=[] 时：
不直接结束任务
触发下一步动作（retry）
3. Retry / Re-plan 机制
首轮检索失败 → 自动切换语义检索：
knowledge_search → knowledge_semantic_search
retry step 已纳入执行计划（plan）
4. 多步执行链路打通

当前系统已具备：

User Input
→ Plan (LLM / Rule-based)
→ Execute Step1
→ Verify
→ Retry Step
→ Verify
→ Final Answer
5. Debug 可观测性

debug=true 时可以看到：

plan
step_results
retry 行为
每一步输出内容
二、测试结果分析（关键验证）
🧪 测试用例
搜索 一个很奇怪的不存在内容abc999
🔍 实际执行过程
Step1：knowledge_search
hits_total = 0
判定：insufficient ✅
行为：触发 retry
Retry1：knowledge_semantic_search
返回若干 hits（score ≈ 0.2~0.34）
实际为弱相关内容（语义漂移）
⚠️ 当前问题

系统最终输出：

任务已完成
step1 成功
retry1 成功

❗ 问题本质

当前系统存在关键缺陷：

❌ 将“执行成功”误判为“答案成功”

实际情况：

维度	状态
Tool Execution	✅ 成功
Result Quality	❌ 不足
Final Answer	❌ 错误（误报成功）
三、当前 M4.3 状态评估
✅ 已完成（Core）

M4.3 核心执行能力已经具备：

Reflection loop（执行后自检）
空结果识别
Retry 触发机制
多步执行链路
Debug 可观测性

👉 结论：M4.3 Core = DONE

⚠️ 未完成（Hardening）

当前缺失的是：

1. 结果质量判定不足
未识别低分 semantic 命中（score≈0.3）
未区分 weak / insufficient
2. 缺少强关键词校验
query 中的 abc999 未出现在任何结果中
系统仍认为命中有效
3. 无 fallback 策略
retry 后仍不足
未进入 fallback
直接输出“任务完成”
4. Final Answer 不符合用户语义

当前输出是：

内部执行日志 ❌
而非用户可读答案 ❌

👉 结论：M4.3 Hardening = IN PROGRESS

四、下一步优化方向（已设计）
🎯 引入 VerifyDecision 结构
status: pass / weak / insufficient / fatal
action: continue / retry / replan / fallback
reasons: []
score: optional
🎯 增加 3 个核心判定规则
1. Semantic Score Threshold
top_score < 0.35 → insufficient
0.35–0.5 → weak
2. 强关键词覆盖检查
query 中关键 token 未出现在 top-k
→ 判定为 insufficient
3. Retry 上限 + Fallback
semantic retry 后仍不足
→ 必须 fallback
🎯 Final Answer 分层输出
状态	输出策略
pass	正常回答
weak	保守回答
insufficient	明确说明未找到
fatal	系统失败说明
五、M4.3 阶段性结论
📌 当前真实进度
模块	状态
Reflection Loop	✅
Retry / Re-plan	✅
Verification（基础）	✅
Verification（质量）	⚠️
Fallback 策略	❌
🧠 总结一句话

M4.3 已完成“会反思”，但还没完成“反思正确”。

六、Roadmap 更新
当前进度
M1 Runtime        ✅
M2 Knowledge      ✅
M2.5 Semantic     ✅
M3 RAG            ✅
M4.1 Planner      ✅
M4.2 Multi-step   ✅
M4.3 Reflection   ✅（Core）
                 ⏳（Hardening）

---

## 2026-04-05 开发记录：SOTA 检索链路重构 → Hybrid Retrieval 接入 → RAG 能力验证

### 一、今日目标

今天的核心目标不是继续堆功能，而是围绕当前 P4 Agent Sandbox 的知识检索与问答主链，做一轮更接近 SOTA 检索系统的结构性重构与验证，重点包括：

1. 从“单一路径 semantic retrieval”升级为更合理的 **metadata-aware retrieval + hybrid retrieval**
2. 让 query 能先经过 **route / rewrite**，再进入检索
3. 让 RAG 不再只依赖 truncated snippet，而是尽可能使用 **full chunk text**
4. 验证当前系统在不同类型问题上的表现，包括：
   - 明确事实型问题
   - 操作流程型问题
   - 概念定义型问题
   - 多阶段里程碑对比型问题

---

### 二、今天完成的核心重构

---

#### 1. metadata 路由能力正式接入主链

今天已经把 metadata 相关能力真正接入到了执行链中，而不是只停留在上传阶段。

当前检索 / RAG 工具已支持以下 metadata filter：

- `domain`
- `file_type`
- `source`

并且在执行阶段通过 `route_query()` 自动为知识类工具注入路由结果。

#### 已实现的效果

- 查询 `ROS2 机械臂抓取流程` 时，会自动路由到 `robotics`
- 查询 `自动驾驶 planning 模块` 时，会自动路由到 `autonomous_driving`
- 查询 `RAG 是什么`、`如何重建知识库` 等时，会路由到 `agent_system`

#### 当前意义

这一步意味着系统已经从“整个知识库无差别搜索”，升级为“先判断问题属于哪个知识域，再缩小检索范围”。

这已经接近现代知识系统中常见的：

- domain routing
- metadata filter
- retrieval scoping

---

#### 2. query rewrite 机制已经接入执行主链

今天已经把 rewrite 能力加入到 orchestrator 的执行过程中。

当前特点：

- 对知识类 query，会在真正调用检索 / RAG 工具前进行 rewrite
- 已支持把部分英文术语、问法补成更适合检索的形式
- 审计日志里已经可以看到：
  - `original_query`
  - `rewritten_query`
  - `rewrite_info`

#### 当前状态

目前 rewrite 还是偏规则型，但链路已经打通，后续可平滑升级为：

- LLM rewrite
- 多候选 rewrite
- query decomposition

#### 当前意义

这一步很关键，因为它意味着系统不再是“拿用户原句直接硬搜”，而是开始具备 query understanding 的前置处理能力。

---

#### 3. `knowledge_search` 已从“文件级 summary 搜索”升级到“chunk 级全文检索”

这是今天非常关键的一次升级。

之前 `knowledge_search` 的全文能力实际上不够强，容易退化成：

- 只在 summary 上找
- 命中不稳定
- 很难定位局部事实

今天已经完成重构：

#### 新能力

- 支持 `mode="text"` 时直接在 **chunk 级文本** 上做 keyword / full-text 搜索
- 每条命中结果带回：
  - `chunk_id`
  - `chunk_index`
  - `section_title`
  - `heading_level`
  - `section_path`
  - `start / end`
  - metadata 字段

#### 已验证的结果

测试：

```bash
全文搜索 gripper
已经可以直接命中：

robotics_grasp_pipeline.md / chunk_0006
robotics_grasp_pipeline.md / chunk_0011
robotics_grasp_pipeline.md / chunk_0010

并且能检出真正包含 gripper 的 chunk，而不是空结果后再 fallback。

当前意义

这一步意味着系统已经具备了真正可用的 chunk-level keyword retrieval，为后面的 Hybrid Retrieval 提供了 keyword 分支基础。

4. Hybrid Retrieval 正式落地

今天已经完成 app/core/hybrid_retrieval.py，并将其接入 RAG 主链。

当前 Hybrid 结构
keyword retrieval：knowledge_search(mode="text")
semantic retrieval：knowledge_semantic_search
fusion：RRF (Reciprocal Rank Fusion)
当前流程
question
→ keyword retrieval
→ semantic retrieval
→ RRF fusion
→ topK hits
→ context builder
→ LLM answer
当前意义

这标志着系统从：

单路语义检索

升级为：

Hybrid Retrieval（keyword + semantic + fusion）

这是一次非常重要的架构升级，已经明显向更现代的 RAG 系统靠近。

5. RAG pipeline 已从 pure semantic 改为 hybrid retrieve

今天已经修改 rag_pipeline.py：

之前：

run_rag_pipeline
→ semantic_retrieve
→ build_context
→ LLM

现在：

run_rag_pipeline
→ hybrid_retrieve
→ build_context
→ LLM

也就是说，RAG 问答现在不是只依赖 embedding 相似度，而是依赖融合后的检索结果。

当前意义

这一步非常关键，因为很多事实型问题在纯 semantic 下容易漏掉，而 hybrid 对：

精确术语
ID / pulse / 参数
短英文 token
关键步骤名

更友好。

6. full chunk text 已成功回填到 RAG context

这是今天最关键的实际效果之一。

之前的失败案例里，RAG 命中了正确 chunk，但传给 LLM 的只是截断 snippet，例如：

Gripper:
- 200 = c

导致模型虽然命中了相关 chunk，但拿不到完整事实，最终回答失败。

今天修复后，full_context 中已经能看到完整内容：

Gripper:
- 200 = closed
- 600 = open
当前意义

这一步说明：

检索命中不再只是“看起来对”
LLM 已经真正拿到了可回答问题的原始证据

这也是今天最实质性的正确性提升。

三、今天解决的关键问题 / Bug
1. 修复 metadata / router 链路不生效问题

今天确认并修复了 orchestrator 中“计算出 routed_args，但实际 tool_call 仍然传 resolved_args”的问题。

修复后：

step_results.output.domain
filtered_file_count
top hits 的 domain 分布

都能体现 routing/filter 已真正生效。

2. 修复 route/preview 接口不可用问题

之前出现：

Invalid HTTP request received
Not Found
路由文件循环 import

今天已经定位并修复，/route/preview 可正常返回：

domain
strategy
notes
3. 修复 metadata.py 语法错误

启动过程中曾因为 metadata.py 中存在非法字符 / 语法残留导致 uvicorn 无法启动，今天已排查并修复。

4. 修复上传时报 sqlite3.OperationalError: no such table: files

问题原因是数据库被手动清空后，启动后未重新正确初始化表结构。

今天已通过 startup() / TaskStore.init() 重新恢复，上传接口重新可用。

5. 修复 router.py 循环 import

曾出现：

ImportError: cannot import name 'route_query' from partially initialized module

今天已定位为模块内部自引起的循环导入，后续已恢复正常。

6. 修复 knowledge_rag_answer 插件加载失败

今天最关键的一次故障定位。

现象：

boot 日志看起来插件系统正常
但实际执行时报：
'knowledge_rag_answer'
tool handler not found: knowledge_rag_answer

通过对 ToolRegistry 和 SafeToolExecutor 加 debug 后确认：

registry 本身没问题
真正原因是：
knowledge_rag_answer 所依赖的 hybrid_retrieval.py 有语法错误
导致插件加载失败
policy 允许该 tool，但 registry 实际没有注册成功

根因最终锁定为：

from __future__ import annotations

没有放在文件最前面。

修复后：

failed plugins = []
knowledge_rag_answer 成功注册
RAG 主链恢复可用
当前意义

这次排查很有价值，因为它验证了：

boot report
registry state
executor call
plugin import failure

之间的完整关系，整个运行时排障能力更清晰了。

四、今天完成的关键测试结果
测试 1：全文搜索 gripper
结果：成功

输出已经变成真正的全文 chunk 检索结果，而不是空结果 + semantic retry。

命中内容包括：

grasp_node
Servo Control
Step 4: Motion Execution
说明
knowledge_search(mode="text") 已真正可用
keyword branch 已落地成功
测试 2：知识问答 gripper 打开和关闭的脉冲值是多少
结果：成功

最终回答：

打开：600
关闭：200
说明

这是今天最重要的 RAG 成功样例，证明：

hybrid retrieval 已接入
full chunk text 已进入 context
LLM 已能基于证据稳定回答

这条测试是今天最重要的正向结果。

测试 3：知识问答 如何重建知识库
结果：成功

最终正确输出了 5 个步骤：

上传文档
构建知识索引
构建文本块
构建知识向量
知识问答验证
说明

这说明 Hybrid Retrieval 不只适合参数型问题，对流程型问题也已经明显优于原先 pure semantic 版本。

测试 4：知识问答 RAG 是什么
结果：成功

输出内容正确，且说明 hybrid 引入后并没有破坏原本已经稳定的概念型问答。

说明

这意味着系统现在在三类问题上都已经出现正向结果：

明确事实型
流程型
概念型
测试 5：知识问答 M1 M2 M3 M4的区别是什么
结果：未通过

当前输出仍为：

命中了 M1 / M2 / M2.5 / M3
但最终仍回答“未在知识库中找到明确答案”
当前判断

这并不是检索完全失败，而是：

M4 没有稳定进入 top context
即便拿到了 M1/M2/M3 chunk，context 仍偏碎片化
当前 context builder 只是简单拼接 topK，缺少：
section grouping
邻近 chunk 合并
对同一文档里连续 section 的组织
verifier 对这类“多段对比型问题”还比较保守
说明

这条测试非常有价值，因为它准确暴露出当前系统下一阶段的瓶颈已经不是“能不能搜到”，而是：

“能不能把多段证据组织成适合回答对比问题的上下文”

这正是下一阶段应该进入的方向。

五、截至今天的系统能力判断
已经明显稳定的能力
Chunk-level keyword retrieval
Semantic retrieval + rerank
Metadata-aware routing/filter
Hybrid Retrieval（keyword + semantic + RRF）
RAG with full evidence context
对明确事实 / 流程 / 概念问题的可用问答
仍然不足的能力
Multi-section comparison
例如：M1 / M2 / M3 / M4 区别
Context Builder 还偏初级
仍是 topK 拼接
Section / title boost 还可以继续强化
RAG verifier 还不能很好处理“部分可答、部分缺失”的问题
Rewrite 目前主要还是 rule-based，不够通用
Hybrid Retrieval 虽已接入，但还未加更细的 chunk/section 合并策略
六、今天阶段性结论

今天这轮开发的意义非常明确：

不是简单修 Bug，而是把系统从一个“能跑的基础 RAG”推进到了一个开始具备现代检索系统形态的 Agent Knowledge Runtime。

从 SOTA 视角看，今天已经完成了以下关键跃迁：

原来：
单一路径 semantic retrieval
+ topK snippet 拼接
+ 命中不稳定

现在：
route / metadata filter
+ query rewrite
+ chunk-level keyword retrieval
+ semantic retrieval
+ RRF hybrid fusion
+ full chunk context
+ RAG answer

也就是说，今天的系统已经明显从：

❌ “基础检索问答 demo”

进化到了：

✅ “具备 SOTA 检索链路雏形的本地 Agent Runtime”

七、当前阶段判断
当前里程碑状态
M1 Runtime Foundation：✅
M2 Knowledge Runtime：✅
M2.5 Semantic Retrieval：✅
M3 RAG Runtime：✅
M4.1 Planner：✅
M4.2 Multi-step：✅
M4.3 Reflection / Verification（Core）：✅
M4.3 Hardening：🟡 持续中
今天对 M3 / M4 的实际推进

今天虽然主要在检索链路上工作，但本质上是在给 M3 RAG Runtime 做一次质量跃迁，同时也为 M4 智能化执行 打基础。

因为：

更好的 retrieval → 更好的 answer quality
更清晰的 routing / rewrite → 更好的 planner/tool use
更强的 evidence context → 更合理的 verifier
八、下一步建议

明天或下一阶段应优先推进：

1. Context Builder 升级

目标：

相邻 chunk 合并
同 section / 同文档聚合
避免 topK 碎片化
2. Section / title boost 强化

目标：

“如何重建知识库”这类问题更稳定地命中 playbook section
“M1 M2 M3 M4区别”这类问题更稳定地命中 roadmap sections
3. Multi-section question 支持

目标：

支持对比型问题
支持汇总型问题
支持“多个阶段 / 多个模块差异”类问答
4. verifier 升级

目标：

区分“部分可答”与“完全不可答”
不要把“已有 80% 正确证据”的回答一律打成失败
5. 后续再考虑 LLM-based rewrite / decomposition

在 rule-based rewrite 先稳定后，再做更强 query understanding。

九、今天一句话总结

今天完成的不是一次小修，而是把 P4 Agent Sandbox 的知识检索主链，正式从“单路语义检索”升级到了“带 routing / rewrite / metadata filter / hybrid retrieval / full-context RAG”的新阶段。

其中最关键的正向验证是：

gripper 打开和关闭的脉冲值是多少：✅ 成功
如何重建知识库：✅ 成功
RAG 是什么：✅ 成功
M1 M2 M3 M4的区别是什么：❌ 暂未解决，但已准确暴露下一阶段瓶颈为 context builder 与 multi-section synthesis

# Dev Log
## 2026-04-11 — M4.5 Context Builder 完成记录

### 今日目标
完成 M4.5 Context Builder 的可用版本，使 RAG 不再只是“检索到什么就直接拼什么”，而是能够：

- 对召回候选进行上下文级重排
- 过滤明显噪声块
- 根据问题类型组织更合理的证据顺序
- 提升复杂问题、区别题、关系题的回答稳定性

---

## 一、今天完成的核心改动

### 1. 引入独立的 Context Builder 模块
已在 `app/core/context_builder.py` 中实现上下文构建逻辑，并在 `rag_pipeline.py` 中接入调用。

当前主链路变为：

```text
Hybrid Retrieval
→ Context Builder
→ Prompt Assembly
→ LLM Answer

不再采用简单的“topK chunk 直接拼接”方式。

2. 实现显式 Context Rerank

在 Context Builder 中新增显式上下文分数 context_score。

当前区分两类分数：

score：原始 retrieval 分数
context_score：进入 prompt 前的上下文排序分数

这意味着系统已经具备两层判断：

这一块和 query 是否相似
这一块是否更值得进入 prompt、是否应该排前面

这是从“纯检索”迈向“检索 + 重排”的关键一步。

3. 实现 query-aware 排序

Context Builder 已可根据问题类型做 section-aware 排序。

当前已支持的粗分类包括：

process（流程类）
architecture（架构类）
compare（区别 / 对比类）
relation（关系类）
general（普通问题）

并根据问题类型对不同 section 进行加权，例如：

System Architecture
Overview
Step x
*_node

从而提升“区别题 / 关系题 / 流程题”的上下文组织质量。

4. 实现噪声过滤

已加入噪声块过滤逻辑，当前会过滤或降权以下类型内容：

Keywords
Failure
Error
Common Issues
Improve ...
过短、无实质信息的块

效果：减少 prompt 污染，节省上下文预算，降低 LLM 被弱相关内容带偏的概率。

5. 扩大 RAG 候选召回规模

将 RAG 调用时的 top_k 从 5 提升到 10。

这个改动非常关键，因为 Context Builder 只有在“关键 chunk 被召回”的前提下，才能进行有效重排。

实践证明：

当 top_k=5 时，一些关键块（如 System Architecture）可能根本进不了候选
当 top_k=10 后，Context Builder 才能把关键块提升到 prompt 前列
二、今天验证通过的能力
Case 1：区别题

测试问题：

知识问答 机械臂抓取流程和系统架构有什么区别？
之前的问题
System Architecture 虽然可能在召回集合里，但原始分数较低
prompt 中常混入 Failure / Error / Improve 等噪声块
最终答案能答对，但更依赖 LLM 的抽象能力，证据支撑不够扎实
现在的表现

在 full_context 中可明确看到：

System Architecture 被提升到第 1 位
Step 1 / Step 2 被保留
Failure / Error / Improve 相关内容被过滤掉
输出中显示 context_score，证明显式 rerank 已生效

示例结果特征：

[1] System Architecture
score=0.043895
context_score=0.893895

这说明系统已经不再按原始检索顺序拼接，而是在进入 prompt 前进行了重排。

结论

区别题从“表面能答”提升到了“有结构化证据支撑地回答”。

Case 2：关系题

测试问题：

知识问答 ROS2 机械臂抓取流程里，world model 和 IK 的关系是什么？
当前上下文组织

full_context 前列已经稳定出现：

System Architecture
ik_solver_node
world_model_node
Step 2: Coordinate Transformation
Overview
Step 3: Inverse Kinematics
这说明

系统已经可以自动组织出一条较完整的证据链：

整体关系：System Architecture
节点职责：world_model_node + ik_solver_node
流程补充：Step 2 + Step 3
最终答案

回答能够明确说明：

World Model 负责像素坐标到世界坐标转换
IK 负责根据目标位姿求解关节角 / 脉冲
前者是后者的重要输入
结论

关系题的证据结构和答案质量都达到较好水平。


新功能！
点击以编辑
📅 Dev Log — 2026-04-12
🧭 今日目标
打通 Multi-domain RAG 全链路
统一 domain → domains 参数体系
实现 Planner → RAG → Retrieval 的端到端运行验证
从“代码完成”推进到“真实运行成功”
✅ 今日完成
1️⃣ RAG Pipeline 完整升级（核心里程碑）

✅ run_rag_pipeline 支持：

domains: list[str]
file_type: str | None
source: str | None

✅ retrieval 调用统一为：

hybrid_retrieve(..., domains=domains)
✅ 输出结构统一：
domains
hits
context
answer

👉 结论：
RAG 主链已完成 multi-domain 改造（代码层完成）

2️⃣ Hybrid Retrieval 架构升级（关键突破）
✅ 引入 RRF 融合（Reciprocal Rank Fusion）
Keyword + Semantic 双路融合
✅ 支持 metadata filter：
domains
file_type
source
✅ 增加字段：
from_keyword
from_semantic
rrf_score
✅ 自动补全：
full_text

👉 当前能力：

Hybrid Retrieval = Keyword + Semantic + RRF Fusion

👉 意义：
已经脱离“简单向量检索”，进入工业级 RAG 检索架构

3️⃣ Semantic Retrieval 对齐
✅ 支持 domains 过滤
✅ metadata fallback（index → meta.json）
✅ 向量检索结构统一
✅ 输出标准化（score / snippet / full_text）
4️⃣ Knowledge Tool 层改造（关键中间层）

涉及：

knowledge_search
knowledge_semantic_search

已完成：

domain → domains
_meta_match → 支持 list 过滤

👉 状态：
✅ 基本完成（已接入 hybrid）

5️⃣ Multi-domain RAG 主链打通（🚀重大里程碑）
✔ 实际运行验证（关键）

执行：

知识问答 端到端自动驾驶系统的核心模块是什么

输出：

status: done
step0 ok: True
domains: ['autonomous_driving']
hits_total: 10
✔ 关键验证点全部通过
✅ Planner 正确识别 domain

✅ Router 成功路由到：

autonomous_driving
✅ RAG pipeline 正常执行
✅ hybrid retrieval 返回结果
✅ context builder 正常拼接
✅ LLM 成功生成答案
🎯 今日最重要结论
Multi-domain RAG 主链：已从“设计完成” → “真实运行成功”

这是一次系统级质变。

❗ 今日核心问题（已解决）
🚨 问题
run_rag_pipeline() got an unexpected keyword argument 'domains'
🎯 根因

👉 运行环境加载了旧版本代码

原因包括：

uvicorn 未重启
pycache 未清
import 指向旧模块
✅ 解决方式
清理缓存
强制重启服务
验证函数 signature

👉 结论：
这是运行态问题，不是架构问题

⚠️ 新暴露问题（非常关键）
❗ Retrieval 质量问题（进入新阶段）

虽然系统已通，但出现：

1. Top Hits 不精准

当前命中内容：

数据标注
虚拟图
泛描述段落

❌ 没有直接命中：

“系统架构”
“核心模块定义”
2. Answer 仍带“模型补全”

当前答案包含：

感知模块
高精地图

👉 但这些并非来自明确结构化证据块

3. 结论
系统问题已从“能不能跑”
升级为
“跑得准不准”
🧠 当前系统能力评估
已完成能力
模块	状态
Multi-domain Routing	✅
Hybrid Retrieval	✅
RRF Fusion	✅
Metadata Filter	✅
Context Builder	✅
Answer Generation	✅
当前短板
模块	状态
Retrieval Ranking	⚠️
Query Rewrite	⚠️
Rerank	❌
Context 精排	⚠️
📊 当前能力等级
M3：已完成（RAG Runtime）
M4.3：已完成（Multi-domain Retrieval）
M4.4：未完成（Rerank + 精排）
🚀 下一步计划
🔥 P0（必须做）
1. Retrieval 精度优化
引入关键词权重：
“核心模块”
“系统组成”
“架构”
降权：
示例
数据说明
工程细节段落
2. Query Rewrite

例如：

原问题：
端到端自动驾驶系统的核心模块是什么

改写为：
自动驾驶系统 核心模块 架构 组成
⭐ P1（系统质变）
3. 引入 Rerank（M4.4）
Cross-encoder rerank
或 LLM rerank

👉 这是下一阶段最关键能力

4. Context Builder 升级
chunk merge
section-aware
token budget 控制
5. Retrieval Debug 能力
输出：
why this hit
why filtered
rerank score
🧩 今日关键突破总结
🔥 最大突破
从：
单 domain + 单检索

到：
Multi-domain + Hybrid + RRF + Structured Context
🧠 本质变化

你今天完成的不是“一个功能”，而是：

从 Demo RAG → Production RAG 的跃迁
📌 明日建议

直接进入：

👉 M4.4 阶段
rerank
retrieval quality control
answer grounding
🧠 一句话总结
今天，你的系统第一次真正具备了“可扩展的知识系统能力”
但还不具备“稳定高质量回答能力”

# 2026-04-18
---

# 🧩 DEV LOG — M0 阶段（Workflow + Skill 闭环）

## 📅 时间范围
2026-04（Milestone M0 阶段）

---

# 🎯 本阶段目标

实现：

- 从 “RAG 问答系统” → “可执行任务的 Agent”
- 支持：
  - Skill 触发
  - Workflow 执行
  - Markdown 交付物输出

---

# ✅ 已完成能力（本阶段新增）

## 1. Skill System v1（已完成）

### 能力
- 支持通过 query 匹配 skill
- 支持 workflow_name 绑定
- 支持结构化 workflow 定义

### 当前实现
- 静态 skill registry
- 手写 skill spec
- 支持 summarize_project_status

---

## 2. Workflow Runtime v1（已完成）

### 能力
- 多 step 顺序执行
- step 状态跟踪（ok / error）
- step output 传递

### 当前实现
- `workflow_runtime.py`
- 支持：
  - collect_inputs
  - rag_analyze
  - generate_report

---

## 3. Task Type Detection v1（已完成）

### 能力
- 区分：
  - 普通 Q&A
  - workflow 任务

### 当前逻辑
- 基于规则判断（关键词 / 结构）

---

## 4. Artifact Generation v1（已完成）

### 能力
- 输出 Markdown 文件
- 支持结构化报告

### 当前实现
- summarize_project_status 输出：
  - 当前阶段
  - 已完成能力
  - 风险
  - 下一步

---

## 5. RAG + Workflow 融合（已完成）

### 能力
- Q&A → 走 RAG
- Task → 走 Workflow

### 当前状态
- 主链路已打通
- Skill 可触发 workflow

---

# ⚠️ 当前问题（关键）

## 1. Workflow 未绑定真实输入（严重）

### 表现
- collect_inputs 只返回 expected_inputs
- 未真正读取：
  - roadmap
  - dev log
  - trace

### 结果
- 后续 step 使用空 context
- LLM 进行“脑补”

---

## 2. Hallucination（高风险）

### 表现
- 输出：
  - “开发中期阶段”
  - “系统按计划推进”
  - “接口需要优化”

### 问题
- 上述内容未出现在输入材料中

---

## 3. RAG 未命中但仍生成

### 表现
- hits = []
- context = ""

但仍输出完整报告

---

## 4. roadmap / dev log 未区分语义

### 问题
- roadmap = 计划
- dev log = 事实

当前系统未区分

---

# 🔧 当前开发重点（M0核心）

## 1. Workflow Input Binding（最高优先级）

必须实现：

- collect_inputs：
  - 真正读取文件
  - 返回 materials

- 构建：
  - materials_context

---

## 2. Step Grounding

每个 step 必须：

- 仅基于 context 分析
- 不允许无依据生成

---

## 3. Artifact 可信性

输出必须：

- 可追溯到输入材料
- 不允许泛化总结
- 不允许“行业模板话”

---

# 🚧 当前进行中

- Workflow Input Binding v1
- Context Grounding
- Step → context 传递机制优化

---

# 📌 下一步计划

## 短期（M0完成前）

1. 实现：
   - collect_inputs → 真实材料读取
2. 改造：
   - rag_analyze → material_analyze
3. 限制：
   - 无证据 → 明确输出“材料中未体现”

---

## 中期（M0之后）

- Memory v1
- Skill 自动生成
- Query Understanding（LLM版本）
- Quality Harness

---

# 📊 当前阶段判断（基于事实）

- 系统已从：
  - “RAG QA系统”
  →
  - “初步 Workflow Agent”

- 当前卡点：
  - ❗ 不在能力
  - ❗ 在 Grounding（证据绑定）

---

# 🧠 关键认知

当前系统状态：

> ✅ 已具备执行能力  
> ❌ 尚未具备“可信执行能力”

---

# 🧪 测试说明（用于 Agent）

本 dev log 用于：

- summarize_project_status workflow 测试
- 验证：
  - 是否基于材料输出
  - 是否避免 hallucination

---

# 2026-04-21

M0 当前测试总结
一、目前 M0 已经完成的模块和功能

从现在的代码、chunk 结果、/agent/run 测试表现来看，M0 不是没做成，而是已经完成了主体框架，并进入 grounded 收尾阶段。

1. 基础知识库链路已经打通

已经具备：

文件上传
文件元数据保存
chunk 构建
embedding 构建
hybrid retrieval
RAG 问答输出

这说明最基础的“文件 → chunk → 向量 → 检索 → 回答”主链路已经是通的。

2. /agent/run 已经能执行 M0 的主入口

你现在已经明确：

M0 阶段先走 /agent/run
不先改 /task/run

这意味着当前系统已经具备：

task route
QA 模式
skill / workflow 模式
基本的 agent 入口调度能力
3. Workflow / Skill 框架已经有雏形

从之前的 summarize_project_status 测试和后续代码修改看，已经实现或部分实现了：

workflow runtime
collect inputs
material analyze
markdown artifact 输出

也就是说，系统已经不只是“问答 demo”，而是开始具备：

基于材料执行任务并生成交付物

这正是 M0 的核心方向。

4. chunk metadata 扩展已经开始生效

你现在看到的 chunk 已经带上了这些字段：

filename
domain
file_type
doc_role
created_at
created_at_iso
created_date
section_title
section_date
people
action_items
due_dates

这一点非常重要，因为它意味着系统已经不再只是“纯文本块检索”，而是开始向：

结构化、可过滤、可约束的检索

靠近。

5. 日期类信息已经能进入 chunk

你刚刚验证出来：

created_at_iso 有值
created_date 有值
section_date 也有值
doc_role=dev_log

说明你这次对未来“会议纪要 / 行动项 / 责任人 / 时间定位”做的铺垫是对的，这一步不是白做，而是很关键。

二、这轮测试发现的主要问题

现在的问题不是“系统完全不能用”，而是：

能命中、能回答，但还不够严格 grounded。

这轮测试暴露出的问题主要有 5 类。

问题 1：用户限定条件还没有真正变成硬过滤

比如你问：

只根据 dev_log_m0_test.md
只根据 roadmap_m0_test.md
只根据 2026-03-15
只根据 当前核心问题

系统虽然“看懂了这句话的大意”，但实际上还没有把这些条件真正下沉成检索过滤条件。

表现就是：

hits 里仍混入其他文件
roadmap 问题会串到 dev log
指定日期时，也会混入别的日期 chunk

这说明：

文件约束、section 约束、日期约束，目前还是“弱语义提示”，不是“强过滤条件”。

问题 2：检索排序仍然容易被高频关键词带偏

例如问：

只根据 roadmap_m0_test.md 中 当前核心问题 回答：现在最大问题是什么

系统却优先召回了 dev log 中关于 “问题”“当前”“系统” 的 chunk。

这说明现在检索排序仍然有明显缺陷：

query 中通用词权重过高
文件名约束权重不够
section 标题命中权重不够
exact match 和 metadata match 还没有压过语义相似噪声
问题 3：roadmap / dev log 的语义角色还没有真正区分开

这点其实你材料里自己也写出来了：

roadmap = 计划
dev log = 事实

但当前系统还没有在检索层和回答层真正落实这一点。

所以出现了：

问 roadmap 的“当前核心问题”，答成 dev log 的“关键认知”
用计划材料时混入事实材料
用事实材料时混入阶段总结材料

这会直接影响 grounded 质量。

问题 4：答案有时对，但过程不干净

比如：

只根据 dev_log_m0_test.md 中 2026-03-15 的内容回答：M3 的目标是什么

最终答案是对的：

M3 的目标是让系统能够用知识库回答问题。

但 hits 里前几条并不干净，前面混进了：

2026-03-23
2026-03-29
roadmap 相关内容

说明现在是：

答案可能答对
但证据链不够纯

而 M0 要求的不是“碰巧答对”，而是：

基于正确材料、按正确约束、输出可信答案。

问题 5：QA 已经能利用 chunk metadata，但还没有“显式使用 metadata filter”

你现在的 chunk 里 metadata 已经有了，这是好事。
但从测试现象看，检索层还没有真的做到：

filename = xxx
section_date = yyyy-mm-dd
doc_role = roadmap/dev_log
section_title = xxx

这种显式过滤。

也就是说：

metadata 已经准备好了，但 retrieval 还没有把它们真正用起来。

三、当前 M0 到底完成到什么程度

我给你一个尽量准确的判断：

M0 已完成的部分
Agent 入口已具备
QA / workflow 基础分流已具备
文件上传与知识库重建已具备
chunk / embedding / hybrid retrieval 已具备
artifact 输出已具备
chunk metadata 扩展已启动
基本 grounded workflow 雏形已形成
M0 尚未完成的关键部分
文件级 hard filter
日期级 hard filter
section 级 hard filter
roadmap / dev log 的角色分离
“只根据……”约束的严格执行
grounded answer 的强校验

所以更准确地说：

M0 主体已完成，当前卡在最后的 Grounding 收尾。

四、后续对策

你现在后续不要再大范围发散，重点就盯住一件事：

把用户问题中的“限定条件”结构化，并真正下沉到检索层。

对策 1：做 Query Constraint Extraction

把这类表达解析出来：

只根据 xxx.md
2026-03-15
当前核心问题
roadmap
dev log

变成结构化约束，例如：

filename = dev_log_m0_test.md
doc_role = dev_log
section_date = 2026-03-15
section_title = 当前核心问题
对策 2：检索层接 metadata filter

在 retrieval 阶段支持：

filename filter
doc_role filter
created_date filter
section_date filter
section_title / section_path filter

并且这些 filter 应优先于纯语义相似度。

对策 3：回答前做 grounded check

如果用户说：

只根据 roadmap_m0_test.md

那最终上下文中如果混入 dev log，就应该：

直接过滤掉
或明确返回“当前命中文本不满足限定条件”

而不是继续生成答案。

对策 4：强化 rerank 规则

后续 rerank 至少要增加这些加权：

文件名完全命中强加权
section_title 完全命中强加权
section_date 命中强加权
doc_role 一致性加权
违反约束的 chunk 降权或剔除
对策 5：把 roadmap / dev log / meeting notes 做角色化

未来你还要接会议纪要、任务描述、责任人、日期、行动项。
所以现在就要把文档角色定清楚：

roadmap = 计划
dev_log = 实际进展
trace = 执行记录
meeting_notes = 会议纪要
task_desc = 任务说明

这样未来才能支持：

按日期问
按责任人问
按行动项问
按阶段问
按计划 vs 实际差异问
五、接下来具体要改什么

按优先级我建议是下面这几块。

第一优先级
query_understanding.py
router.py
rag_pipeline.py 或实际检索入口
hybrid_retrieval.py

目标：

先把 query 中的约束识别出来
再把这些约束传给检索层
第二优先级
knowledge_search / knowledge_semantic_search / 你真正读 chunk_index 的地方
rerank 逻辑所在文件

目标：

让 metadata 真正参与检索与排序
第三优先级
/agent/run 对应的 route 和执行入口
grounded answer / verifier 逻辑

目标：

回答前检查是否真的满足“只根据xxx”的条件
六、现在最准确的一句话总结

M0 的主框架已经搭起来了，当前不是缺功能，而是缺最后一层“按限定条件严格取证”的能力。

所以你现在的重点不是继续加新功能，而是：

把文件名、日期、section、文档角色这些 metadata 真正用进 retrieval 和 grounding。


# 2026-04-25 ～ 2026-04-26

## M0 Grounded Workflow 收尾：从 LLM 总结改为 Facts → Rewrite → Artifact

### 今日核心目标

本阶段目标是继续完善 M0 的 grounded workflow，使 `summarize_project_status` 不再依赖 LLM 直接读全文自由总结，而是改为：

```text
collect_materials
↓
extract_project_facts（规则事实抽取）
↓
rewrite_summary_from_facts（LLM 只做表达整理）
↓
generate_markdown_from_facts

## 一、完成的核心改造

### 1. Workflow 结构重构
summarize_project_status workflow 已从多段 material_analyze 改为三步结构：
collect_inputs
extract_facts
generate_report
后续又增加：

rewrite_summary

最终结构为：

collect_inputs
↓
extract_facts
↓
rewrite_summary
↓
generate_report

### 2. 新增规则事实抽取层

新增函数：

_extract_project_facts_from_materials()

用于从 materials_context 中抽取结构化事实，输出：

{
    "current_stage": [],
    "completed": [],
    "in_progress": [],
    "problems": [],
    "next_steps": [],
}

这一步不调用 LLM，只做规则抽取，目的是保证事实来源可控。

### 3. 新增 Markdown from Facts 输出

新增：

_render_project_status_markdown_from_facts()
_step_generate_markdown_from_facts()

使 Markdown 文件不再直接使用 LLM 生成的大段总结，而是基于结构化 facts 渲染。

### 4. 新增 LLM Rewrite 层

新增：

_step_rewrite_summary_from_facts()
_build_rewrite_summary_prompt()
_parse_rewrite_json()

该层只允许 LLM 做：

去重
合并
归类
改写表达
整理格式

不允许新增事实、不允许推断、不允许扩展材料外内容。

当前结构为：

Rule Extract 控事实
LLM Rewrite 控表达
Rule Render 控输出

## 二、关键问题与修复
### 问题 1：LLM 直接总结仍会产生幻觉

早期版本中，material_analyze 每一步都直接读取完整材料并调用 LLM，总结效果自然，但容易出现：

材料中没有的阶段判断
自行规划优先级
自行补充原因和影响
泛化成项目管理模板语言

因此决定将 LLM 从“事实生成者”降级为“表达整理者”。

### 问题 2：规则抽取初版输出过硬

纯规则版本解决了 hallucination，但输出存在问题：

语言生硬
类似数据库 dump
缺少报告可读性
进行中、下一步、问题项容易混杂

因此引入 rewrite_summary_from_facts，让 LLM 在 facts 边界内优化表达。

### 问题 3：LLM 返回 JSON list，解析层按 string 处理

测试发现 rewrite_summary 返回：

{
  "completed": [
    "Query Understanding（rule-based v1）",
    "Router",
    "RAG Pipeline"
  ]
}

但 _parse_rewrite_json() 按字符串处理，导致输出变成：

['Query Understanding...', 'Router', 'RAG Pipeline']

已修复：

支持 list → Markdown bullet list
支持 string → 原样保留
支持 JSON code block 清洗
支持非法 JSON fallback 到原始 facts

### 问题 4：重复项去重

测试中出现：

- Router（domain + retrieval mode）
- Router
- RAG Pipeline 接入主链路
- RAG Pipeline

已在解析阶段增加规范化去重逻辑，例如：

.replace("（rule-based v1）", "")
.replace("（domain + retrieval mode）", "")
三、当前测试结果

当前生成的项目阶段总结已达到可用状态：

### 当前阶段判断

能够稳定输出：

Milestone M0：First Minimal Work Loop
已完成工作

能够稳定输出：

Query Understanding（rule-based v1）
Router（domain + retrieval mode）
RAG Pipeline 接入主链路
Skill 机制（可触发）
Workflow Runtime v1
Markdown Artifact 输出
当前问题

能够基于材料抽取：

workflow 未真正读取材料
存在无依据生成
roadmap / dev log 未区分
chunk 粒度不稳定
无法做结构过滤
无法按时间 / 类型 / 阶段回答
回答容易泛化
metadata 未进入 retrieval filter
context builder 未使用结构信息
Agent 输出仍存在补全行为

## 三、当前测试结果

当前生成的项目阶段总结已达到可用状态：

当前阶段判断

### 能够稳定输出：

Milestone M0：First Minimal Work Loop
已完成工作

### 能够稳定输出：

Query Understanding（rule-based v1）
Router（domain + retrieval mode）
RAG Pipeline 接入主链路
Skill 机制（可触发）
Workflow Runtime v1
Markdown Artifact 输出
当前问题

### 能够基于材料抽取：

workflow 未真正读取材料
存在无依据生成
roadmap / dev log 未区分
chunk 粒度不稳定
无法做结构过滤
无法按时间 / 类型 / 阶段回答
回答容易泛化
metadata 未进入 retrieval filter
context builder 未使用结构信息
Agent 输出仍存在补全行为
下一步计划

### 能够稳定输出材料中明确出现的未完成项：
Memory 系统
自动 Skill 学习
Quality Harness
LLM-based Query Understanding

## 四、当前能力判断

当前系统已经完成第一个可用的 grounded workflow 闭环：

用户任务
↓
Skill Router
↓
Workflow Runtime
↓
材料读取
↓
事实抽取
↓
受控改写
↓
Markdown Artifact 输出

这标志着系统已经从：

RAG QA 系统

进一步演进为：

可执行任务并生成交付物的 Agent Workflow

## 五、当前仍存在的问题

### 1. 输出偏“事实清单”，报告感仍有限

虽然不再 hallucination，但输出还偏抽取结果，缺少更自然的项目汇报风格。

### 2. next_steps 目前只来自“未完成”段落

当前策略较保守，避免把当前开发重点误写成下一步计划。

但如果用户希望下一步计划更完整，后续需要区分：

明确未完成项
当前开发重点
当前阶段任务
建议性下一步

### 3. current_stage 信息略偏窄

当前主要输出里程碑，后续可把“当前目标”也纳入阶段判断。

### 4. rules 仍依赖文档结构

如果输入文档没有明确的标题结构，例如没有“已完成 / 进行中 / 未完成”，当前规则抽取能力会下降。

后续需要支持更通用的 facts schema。

## 六、阶段性结论

本阶段最大的进展不是生成了一份 Markdown，而是完成了 Agent Workflow 的关键设计转变：

从：

LLM 直接读材料并总结

升级为：

规则抽取事实
↓
LLM 只做受控表达
↓
规则渲染 Artifact

这显著降低了 hallucination 风险，并让输出过程更可控、可调试、可复现。

## 七、下一步建议

### P0：固化当前 M0 Workflow
清理旧的 material_analyze 分支
保留 extract_project_facts + rewrite_summary + generate_markdown_from_facts
增加测试用例
将当前输出作为 M0 验收样例

### P1：增强 facts 抽取泛化能力

支持没有明确标题的文档：

自动识别完成项
自动识别问题项
自动识别计划项
自动识别时间线

### P2：引入 Quality Harness
为生成报告增加自动检查：

是否包含材料外内容
是否有重复项
是否为空
是否符合模板结构
是否满足用户要求

### P3：扩展 Skill 系统

在当前 summarize_project_status 基础上扩展：

summarize_dev_log
generate_weekly_report
summarize_meeting
analyze_project_risk
compare_plan_vs_actual