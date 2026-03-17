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