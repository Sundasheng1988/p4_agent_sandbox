
# 第 1 步：重新上传测试文件

如果你还是用那 4 个测试文件，直接重新上传：

curl -sS -X POST http://127.0.0.1:8000/files/upload \
  -F "file=@/home/sundasheng/p4_agent_sandbox/docs/test_kb/agent_glossary.md"

curl -sS -X POST http://127.0.0.1:8000/files/upload \
  -F "file=@/home/sundasheng/p4_agent_sandbox/docs/test_kb/architecture.md"

curl -sS -X POST http://127.0.0.1:8000/files/upload \
  -F "file=@/home/sundasheng/p4_agent_sandbox/docs/test_kb/ops_playbook.md"

curl -sS -X POST http://127.0.0.1:8000/files/upload \
  -F "file=@/home/sundasheng/p4_agent_sandbox/docs/test_kb/roadmap.md"

然后确认：

curl -sS http://127.0.0.1:8000/files | python -m json.tool

应该能看到 4 条文件记录。

# 第 2 步：构建知识索引
curl -sS -X POST http://127.0.0.1:8000/task/run \
-H "Content-Type: application/json" \
-d '{"user_input":"构建知识索引","debug":true}' \
| python -m json.tool

# 第 3 步：构建文本块
curl -sS -X POST http://127.0.0.1:8000/task/run \
-H "Content-Type: application/json" \
-d '{"user_input":"构建文本块","debug":true}' \
| python -m json.tool

# 第 4 步：构建知识向量
curl -sS -X POST http://127.0.0.1:8000/task/run \
-H "Content-Type: application/json" \
-d '{"user_input":"构建知识向量","debug":true}' \
| python -m json.tool

# 第 5 步：再测试语义搜索
curl -sS -X POST http://127.0.0.1:8000/task/run \
-H "Content-Type: application/json" \
-d '{"user_input":"语义搜索 如何重建知识库","debug":true}' \
| python -c "import sys,json;print(json.dumps(json.load(sys.stdin),indent=2,ensure_ascii=False))"