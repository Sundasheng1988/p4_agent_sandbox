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

### 下一阶段


M4 Agent Intelligence


计划能力：

- Planning
- Multi-step Tool Use
- Memory
- Tool reasoning

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