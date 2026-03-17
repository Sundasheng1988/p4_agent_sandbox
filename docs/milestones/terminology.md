# Runtime
也就是：

程序在“运行过程中”
负责管理执行的一整套机制

不是代码本身，而是：

代码是怎么被执行的

比如 Python：

你写的代码：

print("hello")

真正让它运行的是：

Python Runtime

Python Runtime 负责：

解析代码

执行函数

管理内存

调用库

返回结果

# Knowledge Runtime
Knowledge Runtime 指系统 在运行时如何管理知识数据。

主要能力：

文件
↓
解析
↓
索引
↓
搜索

包含功能：

File Parsing

Knowledge Index

Incremental Build

Summary Search

Full Text Search

对应 Roadmap 阶段：

M2 Knowledge Runtime

# 3 Semantic Runtime
Semantic Runtime 指系统 使用向量语义检索知识的运行机制。

流程：

query
↓
embedding
↓
vector similarity
↓
top-k retrieval

主要能力：

Chunking

Embedding

Vector Index

Semantic Search

对应 Roadmap 阶段：

M2.5 Semantic Retrieval Runtime

# 4 Chunk
Chunk 是 文档被切分后的文本片段。

长文档需要拆分为多个小块，才能进行 embedding 和语义检索。

流程：

document
↓
text split
↓
chunk_0001
chunk_0002
chunk_0003

每个 chunk 通常包含：

500 – 1000 字符

Chunk 数据保存在：

artifacts/chunks/

# 5 Embedding
Embedding 指：

将文本转换为数字向量的过程。

例如：

文本：

rabbit

转换为：

[0.12, -0.45, 0.33, ...]

在本项目中使用模型：

sentence-transformers/all-MiniLM-L6-v2

参数：

vector dimension = 384

Embedding 主要用于：

语义搜索

文本相似度计算

RAG 检索

# 6 Dense Vector
Dense Vector（稠密向量）是 embedding 生成的向量表示。

例如：

[0.13, -0.22, 0.41, ...]

特点：

每个维度都有数值

用于语义相似度计算

在本项目中：

vector_dim = 384

向量保存在：

artifacts/vectors/

# 7 Vector Index
Vector Index 是 向量检索的索引结构。

用于记录：

chunk → vector

关系。

项目中的结构：

artifacts/vector_index.json

记录：

file_id

chunk_count

vector_count

record_path

# 8 Vector Manifest

Vector Manifest 用于记录 单个文件的向量信息。

位置：

artifacts/vector_manifests/

内容示例：

file_id
vector_count
chunk_ids
vector_paths

作用：

文件 → chunks → vectors

映射关系。

# 9 Artifacts

Artifacts 指系统运行过程中产生的 中间数据和输出结果。

本项目 artifacts 结构：

artifacts/
│
├─ chunks/
├─ vectors/
├─ vector_manifests/
├─ chunk_index.json
├─ vector_index.json
└─ knowledge_index.json

这些文件属于：

runtime data

而不是源码。

# 10 Semantic Search

Semantic Search（语义搜索）指：

根据文本含义而不是关键词匹配进行搜索。

流程：

query
↓
embedding
↓
vector similarity
↓
top-k results

在项目中使用：

cosine similarity

进行向量相似度计算。

工具：

knowledge_semantic_search

# 11 Cosine Similarity

Cosine Similarity 是向量相似度计算方法。

公式：

similarity = dot(a, b) / (|a| * |b|)

结果范围：

-1 ～ 1

含义：

值	含义
1	完全相似
0	无关
-1	完全相反

在语义检索中通常：

0.4 – 0.8

表示较高相关性。

# 12 Top-K Retrieval

Top-K Retrieval 指：

从所有向量中选取相似度最高的 K 个结果。

流程：

query vector
↓
calculate similarity
↓
sort
↓
top-k results

例如：

top-5
top-10

返回最相关的文本 chunk。

# 13 RAG（Retrieval Augmented Generation）

RAG 是一种 AI 架构：

Retrieval
+
LLM Generation

流程：

User Query
↓
Semantic Search
↓
Top-k Chunks
↓
Context Assembly
↓
LLM Reasoning
↓
Answer Generation

对应 Roadmap：

M3 RAG Runtime

# 14 Agent

Agent 指能够：

理解任务
↓
规划步骤
↓
调用工具
↓
执行任务

的智能系统。

Agent 通常包含：

Planning

Tool Use

Memory

Reasoning

对应 Roadmap：

M4 Agent Intelligence

# 15 P4 Agent Sandbox

P4 Agent Sandbox 是一个 本地 Agent Runtime 实验平台。

目标是构建：

Agent Runtime
+
Knowledge Runtime
+
Semantic Retrieval
+
RAG
+
Agent Intelligence

Roadmap：

M1 Runtime Foundation
M2 Knowledge Runtime
M2.5 Semantic Retrieval Runtime
M3 RAG Runtime
M4 Agent Intelligence
总结

本项目技术栈可以简化为：

Runtime
↓
Knowledge
↓
Semantic Retrieval
↓
RAG
↓
Agent Intelligence

系统能力逐步从：

工具执行系统

发展为：

智能 Agent 系统