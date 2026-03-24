# Ops Playbook

## 如何启动服务
先激活 .venv，然后运行 uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload。

## 如何重建知识库
重建知识库的步骤如下：
1. 上传文档
2. 执行“构建知识索引”
3. 执行“构建文本块”
4. 执行“构建知识向量”
5. 执行“知识问答 xxx”验证结果

## 如何清空知识库运行数据
删除 uploads、artifacts/chunks、artifacts/vectors、artifacts/vector_manifests、artifacts 下的索引 json，以及 db/app.db。