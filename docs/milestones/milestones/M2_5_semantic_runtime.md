# M2.5 Semantic Runtime

## 1. Milestone Goal

在 M2 Knowledge Runtime 的基础上，引入 **向量语义检索能力**。

系统能够：

- 将文本 chunk 转换为 dense vector
- 将向量持久化到 artifacts
- 构建 vector index
- 支持 semantic search

实现：
query → embedding → similarity → top-k retrieval

---

## 2. Architecture Position

M2.5 Semantic Runtime 在系统中的位置：

User Input
↓
FastAPI
↓
Orchestrator
↓
SafeToolExecutor
↓
Tools
    ├─ knowledge_build_embeddings
    └─ knowledge_semantic_search
↓
Artifacts
    ├─ vectors
    ├─ vector_manifests
    └─ vector_index.json

---

# 2. New Capabilities

新增工具：

### knowledge_build_embeddings

功能：
chunk → embedding → vector

流程：
chunk_index.json
↓
SentenceTransformer
↓
vector files (.npy)
↓
vector_manifests
↓
vector_index.json

输出：
artifacts/vectors/
artifacts/vector_manifests/
artifacts/vector_index.json

---

### knowledge_semantic_search

功能：
query → embedding → similarity → top-k retrieval

流程：
query
↓
embed_query()
↓
load vectors
↓
cosine similarity
↓
top-k results

返回结果：
filename
chunk_id
score
snippet

---

# 3. Embedding Model

使用模型：
sentence-transformers/all-MiniLM-L6-v2

参数：
vector_dim = 384
normalize = true

模型加载方式：
SentenceTransformer(local_model_path)

模型本地路径：
~/models/all-MiniLM-L6-v2

---

# 4. Vector Storage Layout

artifacts/
│
├─ vectors/
│ ├─ fileid_0001.npy
│ ├─ fileid_0002.npy
│
├─ vector_manifests/
│ ├─ fileid.vectors.json
│
└─ vector_index.json

说明：

| 文件 | 用途 |
|----|----|
| vectors | 每个 chunk 的 embedding |
| vector_manifests | 单文件向量索引 |
| vector_index.json | 全局向量索引 |

关系：
file → chunks → embeddings → vector manifests → vector index

---

# 5. Semantic Retrieval Flow

User Query
↓
embed_query()
↓
vector similarity
↓
top-k retrieval
↓
result snippets

Similarity metric：

cosine similarity

---

# 6. Example Run

构建向量：

```bash
curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"构建知识向量"}'

结果：

files_total = 4
total_vectors = 77
vector_dim = 384

curl -sS -X POST http://127.0.0.1:8000/task/run \
  -H "Content-Type: application/json" \
  -d '{"user_input":"语义搜索 rabbit"}'

返回：
top-k semantic hits

返回结构：

{
  filename
  chunk_id
  score
  snippet
}

# 7. Milestone Result

M2.5 完成后，系统能力：

能力	状态
chunk index	✅
embeddings	✅
vector storage	✅
semantic search	✅

系统正式进入：

Vector Retrieval Runtime

为 M3 RAG Runtime 提供基础。