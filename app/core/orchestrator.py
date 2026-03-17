# orchestrator.py
from __future__ import annotations
import re
import uuid
from typing import List
from app.core.models import TaskRequest, TaskState, ToolCall, StepResult
from app.core.audit import AuditLogger
from app.tools.base import SafeToolExecutor
from app.core.storage import TaskStore


class Orchestrator:
    def __init__(self, tool_exec: SafeToolExecutor, audit: AuditLogger, store: TaskStore):
        self.tool_exec = tool_exec
        self.audit = audit
        self.store = store

    def new_trace_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def plan(self, state: TaskState) -> List[ToolCall]:
        """
        C1: rule-based planner (no LLM).
        Map user utterance -> tool calls.
        """
        t = state.user_input.strip()
        plan: List[ToolCall] = []

        # --- extract file_id (8-32 hex) ---
        m_id = re.search(r"\b([0-9a-f]{8,32})\b", t.lower())
        file_id = m_id.group(1) if m_id else None

        # --- extract summary length like "120字" ---
        m_len = re.search(r"(\d{2,4})\s*字", t)
        summary_chars = int(m_len.group(1)) if m_len else 400
        summary_chars = max(50, min(summary_chars, 2000))

        # --- extract fulltext search query like "全文搜索 xxx" / "搜索正文 xxx" ---
        m_q_text = re.search(r"(全文搜索|搜索正文)\s+(.+)$", t)
        search_q_text = m_q_text.group(2).strip() if m_q_text else None

        # --- extract search query like "搜索 xxx" / "查找 xxx" ---
        m_q = re.search(r"(搜索|查找|检索)\s+(.+)$", t)
        search_q = m_q.group(2).strip() if m_q else None

        # =============================
        # 1) 列出 sandbox 目录
        # =============================
        if "列出" in t and "uploads" in t:
            plan.append(ToolCall(name="file_list", args={"path": "/home/sundasheng/p4_agent_sandbox/uploads"}))
            return plan

        if "列出" in t and "logs" in t:
            plan.append(ToolCall(name="file_list", args={"path": "/home/sundasheng/p4_agent_sandbox/logs"}))
            return plan

        if "列出" in t and "artifacts" in t:
            plan.append(ToolCall(name="file_list", args={"path": "/home/sundasheng/p4_agent_sandbox/artifacts"}))
            return plan

        if "列出" in t and "db" in t:
            plan.append(ToolCall(name="file_list", args={"path": "/home/sundasheng/p4_agent_sandbox/db"}))
            return plan

        # =============================
        # 2) 列出已上传文件（SQLite）
        # =============================
        if ("列出" in t or "查看" in t) and ("上传" in t or "文件" in t):
            plan.append(ToolCall(name="files_list", args={"limit": 50}))
            return plan

        # =============================
        # 3) 文件元信息
        # =============================
        if file_id and ("信息" in t or "meta" in t or "元信息" in t):
            plan.append(ToolCall(name="file_meta", args={"file_id": file_id}))
            return plan

        # =============================
        # 4) 解析文件（txt/pdf/docx -> text）
        # =============================
        if file_id and ("解析" in t or "parse" in t):
            plan.append(
                ToolCall(
                    name="file_parse_by_id",
                    args={"file_id": file_id, "max_chars": 20000},
                )
            )
            return plan

        # =============================
        # 5) 读取文件内容
        # =============================
        if file_id and ("读取" in t or "读" in t or "打开" in t or "内容" in t):
            plan.append(
                ToolCall(
                    name="file_read_by_id",
                    args={
                        "file_id": file_id,
                        "max_bytes": 200000
                    }
                )
            )
            return plan
        
        # =============================
        # 6) 总结/摘要文件
        # =============================
        if file_id and ("总结" in t or "摘要" in t or "summary" in t):
            plan.append(
                ToolCall(
                    name="file_summary_by_id",
                    args={
                        "file_id": file_id,
                        "max_chars": 20000,      # 给 parse 用的上限（你 tool 里这么写的）
                        "summary_chars": summary_chars,    # 输出摘要长度
                    },
                )
            )
            return plan
        
        # =============================
        # 7) 构建知识索引
        # =============================
        if "构建知识索引" in t or "生成知识库" in t:
            plan.append(
                ToolCall(
                    name="knowledge_build_index",
                    args={}
                )
            )
            return plan
        
        # =============================
        # 8.1) 构建文本 chunks（M2.5.1）
        # =============================
        if "构建文本块" in t or "构建chunks" in t or "构建 chunk" in t:
            plan.append(
                ToolCall(
                    name="knowledge_build_chunks",
                    args={
                        "limit": 500,
                        "max_chars": 50000,
                        "chunk_size": 800,
                        "overlap": 120,
                        "force": False,
                    }
                )
            )
            return plan

        # =============================
        # 8.2) 构建 embeddings（M2.5.2）
        # =============================
        if (
            "构建知识向量" in t
            or "构建向量" in t
            or "构建 embedding" in t.lower()
            or "构建 embeddings" in t.lower()
        ):
            plan.append(
                ToolCall(
                    name="knowledge_build_embeddings",
                    args={
                        "limit": 500,
                        "model_name": "all-MiniLM-L6-v2",
                        "normalize": True,
                        "max_chunks_per_file": 5000,
                        "force": False,
                    }
                )
            )
            return plan
        
        # =============================
        # 8.6) RAG 问答（M3）
        # =============================
        m_rag = re.search(r"(知识问答|根据知识库回答|回答问题)\s+(.+)$", t)
        rag_q = m_rag.group(2).strip() if m_rag else None

        if rag_q:
            plan.append(
                ToolCall(
                    name="knowledge_rag_answer",
                    args={
                        "question": rag_q,
                        "top_k": 5,
                        "max_context_chars": 4000,
                        # 这里改成你本机 Ollama 已经 pull 下来的 Qwen 模型名
                        "model_name": "qwen2.5:7b-instruct",
                    },
                )
            )
            return plan

        # =============================
        # 9) 语义搜索（M2.5.2）
        # =============================
        m_q_sem = re.search(r"(语义搜索|semantic search)\s+(.+)$", t, re.IGNORECASE)
        search_q_sem = m_q_sem.group(2).strip() if m_q_sem else None

        if search_q_sem:
            plan.append(
                ToolCall(
                    name="knowledge_semantic_search",
                    args={"query": search_q_sem, "limit": 10},
                )
            )
            return plan

        # =============================
        # 10) 全文搜索（M2-4.2）
        # =============================
        if search_q_text:
            plan.append(
                ToolCall(
                    name="knowledge_search",
                    args={"query": search_q_text, "limit": 10, "mode": "text"},
                )
            )
            return plan
        

        # =============================
        # 11) 搜索知识库（M2-4.1）
        # =============================
        if search_q:
            plan.append(
                ToolCall(
                    name="knowledge_search",
                    args={"query": search_q, "limit": 10, "mode": "summary"},
                )
            )
            return plan

        return plan
    
    def verify(self, state: TaskState) -> bool:
        return all(r.ok for r in state.step_results)

    def report(self, state: TaskState) -> str:
        if not state.plan:
            return (
                f"收到：{state.user_input}\n"
                f"（C1 runtime 已就绪：policy/audit/tool wrapper/state machine）\n"
                f"你可以试试：列出已上传文件 / 文件 <id> 信息 / 读取 <id>"
            )

        # ===== RAG问答友好输出 =====
        if len(state.plan) == 1 and state.plan[0].name == "knowledge_rag_answer":
            res = state.step_results[0]

            if not res.ok:
                return f"知识问答失败：{res.error}"

            output = res.output if isinstance(res.output, dict) else {}
            question = output.get("question", state.user_input)
            answer = output.get("answer", "")
            hits = output.get("hits", []) or []

            lines = []
            lines.append(f"问题：{question}")
            lines.append("")
            lines.append("回答：")
            lines.append(answer if answer else "未生成回答")

            if hits:
                lines.append("")
                lines.append("来源：")
                for h in hits[:3]:
                    filename = h.get("filename", "")
                    chunk_id = h.get("chunk_id", "")
                    score = h.get("score", "")
                    lines.append(f"- {filename} / {chunk_id} / score={score}")

            return "\n".join(lines)

        # ===== 默认调试输出 =====
        lines = []

        for i, (call, res) in enumerate(zip(state.plan, state.step_results), start=1):
            lines.append(f"[{i}] tool={call.name} ok={res.ok}")

            if res.ok:
                lines.append(str(res.output))
            else:
                lines.append(f"error: {res.error}")

        return "\n".join(lines)
    
    def to_user_response(self, state: TaskState, debug: bool = True) -> dict:
        """
        debug=True  -> 返回完整调试信息
        debug=False -> 返回面向用户的精简结果
        """
        data = {
            "trace_id": state.trace_id,
            "user_input": state.user_input,
            "final_answer": state.final_answer,
            "status": state.status,
        }
    
        if debug:
            data["plan"] = [c.model_dump() for c in state.plan]
            data["step_results"] = [r.model_dump() for r in state.step_results]

        return data

    async def run(self, req: TaskRequest) -> TaskState:
        trace_id = self.new_trace_id()
        state = TaskState(trace_id=trace_id, user_input=req.user_input, status="planning")

        self.audit.write(trace_id, "task_start", {"user_input": req.user_input})
        await self.store.create_task(trace_id, req.user_input)

        try:
            # PLAN
            state.plan = self.plan(state)
            self.audit.write(trace_id, "plan", {"plan": [c.model_dump() for c in state.plan]})

            # EXECUTE
            state.status = "executing"
            await self.store.update_task(trace_id, state.status)

            for call in state.plan:
                try:
                    out = await self.tool_exec.call(trace_id, call.name, call.args)
                    state.step_results.append(StepResult(ok=True, output=out))
                except Exception as e:
                    state.step_results.append(StepResult(ok=False, error=str(e)))

            # VERIFY
            state.status = "verifying"
            await self.store.update_task(trace_id, state.status)
            ok = self.verify(state)

            # REPORT
            state.status = "reporting"
            await self.store.update_task(trace_id, state.status)

            state.final_answer = self.report(state)
            state.status = "done" if ok else "failed"

            self.audit.write(trace_id, "task_end", {"status": state.status})
            await self.store.update_task(trace_id, state.status, ended=True)
            return state

        except Exception as e:
            state.status = "failed"
            state.final_answer = f"运行失败：{e}"
            self.audit.write(trace_id, "task_crash", {"error": str(e)})
            await self.store.update_task(trace_id, state.status, error=str(e), ended=True)
            return state
