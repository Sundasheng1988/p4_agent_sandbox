User Input
↓
FastAPI
↓
Orchestrator
↓
SafeToolExecutor
↓
Tools
↓
Artifacts / SQLite


## 4/14
你未来理想的架构应该是这样
User Query
  ↓
Query Understanding
  - query_type
  - entity / action / intent
  - strong tokens
  ↓
Router
  - rule hints
  - domain profile matching
  - optional LLM routing
  ↓
Candidate Domains Top-K
  ↓
Multi-domain Retrieval
  - keyword
  - semantic
  - hybrid fusion
  ↓
Rerank
  ↓
Context Builder
  ↓
Verifier
  - check token coverage
  - check domain concentration
  - check noise
  ↓
Answer 