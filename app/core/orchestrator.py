# orchestrator.py
from __future__ import annotations
import re
import uuid
from typing import List
from app.core.models import TaskRequest, TaskState, ToolCall, StepResult
from app.core.audit import AuditLogger
from app.tools.base import SafeToolExecutor
from app.core.storage import TaskStore
from app.core.planner import plan_with_llm
from app.core.verifier import verify_state
from app.core.router import route_query
from app.core.query_rewriter import rewrite_query


class Orchestrator:
    def __init__(self, tool_exec: SafeToolExecutor, audit: AuditLogger, store: TaskStore):
        self.tool_exec = tool_exec
        self.audit = audit
        self.store = store

    def new_trace_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def plan_rule_based(self, state: TaskState) -> List[ToolCall]:
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
        # 6.5) 清空/重置知识库：先区分“问”还是“执行”
        # =============================

        is_question_like = any(x in t for x in ["如何", "怎么", "步骤", "是什么", "为什么", "文档里", "根据知识库回答"])
        is_reset_topic = (
            "重置知识库" in t
            or "清空知识库" in t
            or "重建前清空知识库" in t
            or "reset knowledge" in t.lower()
            or "清空知识库运行数据" in t
            or "重置知识库运行数据" in t
        )
        is_explicit_action = (
            "现在帮我清空" in t
            or "立即清空" in t
            or "直接清空" in t
            or "执行清空" in t
            or "帮我清空" in t
            or "现在帮我重置" in t
            or "立即重置" in t
            or "直接重置" in t
            or "执行重置" in t
            or "帮我重置" in t
        )

        # 先处理：问“如何清空/怎么清空” -> 这是知识问答，不是执行动作
        if is_question_like and is_reset_topic:
            plan.append(
                ToolCall(
                    name="knowledge_rag_answer",
                    args={
                        "question": t,
                        "top_k": 10,
                        "max_context_chars": 4000,
                        "model_name": "qwen2.5:7b-instruct",
                    },
                )
            )
            return plan

        # 只有明确执行动作时，才允许真正 reset
        if is_explicit_action and is_reset_topic:
            plan.append(
                ToolCall(
                    name="knowledge_reset",
                    args={
                        "reset_db": True,
                        "reset_artifacts": True,
                        "reset_logs": False,
                        "reset_uploads": False,
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
                        "top_k": 10,
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
    
    def plan(self, state: TaskState) -> List[ToolCall]:
        cfg = self.tool_exec.ctx.config
        planner_cfg = getattr(cfg, "planner", None)

        mode = getattr(planner_cfg, "mode", "rule") if planner_cfg else "rule"
        model_name = getattr(planner_cfg, "model_name", "qwen2.5:7b-instruct") if planner_cfg else "qwen2.5:7b-instruct"
        timeout = int(getattr(planner_cfg, "timeout", 60)) if planner_cfg else 60

        if mode != "llm":
            self.audit.write(state.trace_id, "planner_mode", {"mode": "rule"})
            return self.plan_rule_based(state)

        try:
            allowed_names = sorted(self.tool_exec.ctx.config.policy.allow_tools)

            plan, meta = plan_with_llm(
                user_input=state.user_input,
                model_name=model_name,
                timeout=timeout,
                allowed_tool_names=allowed_names,
            )

            self.audit.write(
                state.trace_id,
                "planner_llm",
                {
                    "mode": "llm",
                    "meta": meta,
                    "plan": [c.model_dump() for c in plan],
                },
            )

            if not plan:
                fallback_plan = self.plan_rule_based(state)
                self.audit.write(
                    state.trace_id,
                    "planner_fallback",
                    {
                        "reason": "llm_empty_or_invalid_plan",
                        "fallback_plan": [c.model_dump() for c in fallback_plan],
                    },
                )
                return fallback_plan

            return plan

        except Exception as e:
            fallback_plan = self.plan_rule_based(state)
            self.audit.write(
                state.trace_id,
                "planner_fallback",
                {
                    "reason": f"llm_exception: {e}",
                    "fallback_plan": [c.model_dump() for c in fallback_plan],
                },
            )
            return fallback_plan
    
    def _resolve_ref(self, value: str, context: dict):
        """
        支持:
        $step1.output
        $step1.output.hits
        $step2.output.answer
        """
        if not isinstance(value, str) or not value.startswith("$"):
            return value

        expr = value[1:]  # 去掉 $
        parts = expr.split(".")

        if not parts:
            return value

        data = context.get(parts[0])
        for p in parts[1:]:
            if isinstance(data, dict):
                data = data.get(p)
            else:
                return None

        return data

    def _resolve_args(self, args: dict, context: dict) -> dict:
        resolved = {}

        for k, v in (args or {}).items():
            if isinstance(v, str) and v.startswith("$"):
                resolved[k] = self._resolve_ref(v, context)
            else:
                resolved[k] = v

        return resolved
    
    def _inject_route_args(self, call_name: str, resolved_args: dict) -> dict:
        """
        对知识类检索/问答工具自动注入 route 结果。
        当前处理：
        - knowledge_search
        - knowledge_semantic_search
        - knowledge_rag_answer
        """
        args = dict(resolved_args or {})

        route_text = None

        if call_name in {"knowledge_search", "knowledge_semantic_search"}:
            route_text = str(args.get("query", "")).strip()
        elif call_name == "knowledge_rag_answer":
            route_text = str(args.get("question", "")).strip()

        if not route_text:
            return args

        route = route_query(route_text)

        if "domains" not in args:
            args["domains"] = route.domains
        if "file_type" not in args:
            args["file_type"] = route.file_type
        if "source" not in args:
            args["source"] = route.source

        return args
    
    def _rewrite_and_inject_route_args(self, call_name: str, resolved_args: dict) -> tuple[dict, dict]:
        """
        对知识类检索/问答工具先做 query rewrite，再做 route 注入。

        返回:
        - final_args: 最终用于执行 tool 的参数
        - rewrite_info: 记录 rewrite 详情，便于 audit/debug
        """
        args = dict(resolved_args or {})
        rewrite_info = {
            "applied": False,
            "rewrite_mode": None,
            "original_query": None,
            "rewritten_query": None,
            "reason": "",
            "meta": {},
        }

        query_key = None
        original_text = None

        if call_name in {"knowledge_search", "knowledge_semantic_search"}:
            query_key = "query"
            original_text = str(args.get("query", "")).strip()

        elif call_name == "knowledge_rag_answer":
            query_key = "question"
            original_text = str(args.get("question", "")).strip()
    
        else:
            # 非知识检索类工具，不做 rewrite/route
            return args, rewrite_info

        if not original_text:
            return args, rewrite_info

        rw = rewrite_query(
            original_text,
            mode="rule",
            model_name="qwen2.5:7b-instruct",
            timeout=30,
        )

        rewritten_text = str(rw.get("rewritten_query", "")).strip() or original_text

        rewrite_info = {
            "applied": bool(rw.get("applied", False)),
            "rewrite_mode": rw.get("rewrite_mode"),
            "original_query": rw.get("original_query"),
            "rewritten_query": rewritten_text,
            "reason": rw.get("reason", ""),
            "meta": rw.get("meta", {}),
        }

        # rewrite 后回填
        args[query_key] = rewritten_text

        # route
        route = route_query(rewritten_text)

        if "domains" not in args:
            args["domains"] = route.domains
        if "file_type" not in args:
            args["file_type"] = route.file_type
        if "source" not in args:
            args["source"] = route.source

        return args, rewrite_info

    async def _run_verified_retry(self, trace_id: str, state: TaskState, suggested_plan: List[ToolCall]) -> None:
        """
        M4.3 第一版：
        只执行 verifier 给出的 retry plan，
        执行结果直接追加到现有 step_results 中。
        """
        if not suggested_plan:
            return
        
        # TODO: 后续如果 verifier retry 需要引用原步骤结果，
        # 这里要把主执行上下文传进来，而不是重新创建空 context。
        context = {}

        for i, call in enumerate(suggested_plan, start=1):
            try:
                resolved_args = self._resolve_args(call.args, context)
                final_args, rewrite_info = self._rewrite_and_inject_route_args(call.name, resolved_args)

                self.audit.write(
                    trace_id,
                    "verify_retry_step",
                    {
                        "step_id": call.id or f"retry{i}",
                        "tool": call.name,
                        "raw_args": call.args,
                        "resolved_args": resolved_args,
                        "final_args": final_args,
                        "rewrite_info": rewrite_info,
                    },
                )

                out = await self.tool_exec.call(trace_id, call.name, final_args)
                state.plan.append(call)
                state.step_results.append(StepResult(ok=True, output=out))

                context_key = call.id or f"retry{i}"
                context[context_key] = {
                    "tool": call.name,
                    "args": final_args,
                    "output": out,
                    "rewrite_info": rewrite_info,
                }

            except Exception as e:
                state.plan.append(call)
                state.step_results.append(StepResult(ok=False, error=str(e)))
                break
    
    def verify_basic(self, state: TaskState) -> bool:
        return all(r.ok for r in state.step_results)

    def report(self, state: TaskState) -> str:
        if not state.plan:
            return (
                f"收到：{state.user_input}\n"
                f"（C1 runtime 已就绪：policy/audit/tool wrapper/state machine）\n"
                f"你可以试试：列出已上传文件 / 文件 <id> 信息 / 读取 <id>"
            )
        
        verify_result = state.verify_result or {}
        verify_result_after_retry = state.verify_result_after_retry or {}
        final_verify = verify_result_after_retry or verify_result
        final_verify_reason = final_verify.get("reason", "")

        # ===== 1) 单步 RAG：成功时给用户友好答案 =====
        if (
            len(state.plan) == 1
            and state.plan[0].name == "knowledge_rag_answer"
            and state.status == "done"
        ):
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
        
        # ===== 1.5) 单步 RAG：最终失败时给清晰说明 =====
        if (
            len(state.plan) == 1
            and state.plan[0].name == "knowledge_rag_answer"
            and state.status == "failed"
        ):
            res = state.step_results[0]

            if not res.ok:
                return f"知识问答失败：{res.error}"

            output = res.output if isinstance(res.output, dict) else {}
            question = output.get("question", state.user_input)
            answer = str(output.get("answer", "")).strip()

            lines = []
            lines.append(f"问题：{question}")
            lines.append("")

            if "未在知识库中找到明确答案" in answer:
                lines.append("结果：未在知识库中找到可靠答案。")
                lines.append("")
                lines.append("原因：检索虽然返回了一些相似内容，但校验阶段判断这些内容与问题不够相关。")
            else:
                lines.append("结果：答案生成完成，但未通过可靠性校验。")

            return "\n".join(lines)

        # ===== 2) 单步搜索：成功时给简洁摘要 =====
        if len(state.plan) == 1 and state.plan[0].name in {"knowledge_search", "knowledge_semantic_search"}:
            call = state.plan[0]
            res = state.step_results[0]

            if not res.ok:
                return f"{call.name} 执行失败：{res.error}"

            output = res.output if isinstance(res.output, dict) else {}
            hits = output.get("hits", []) or []
            query = output.get("query", call.args.get("query", state.user_input))

            lines = []
            lines.append(f"查询：{query}")
            lines.append("")

            if state.status == "failed":
                lines.append("结果：未找到可靠结果。")
            
                if final_verify_reason == "strong_token_not_covered":
                    lines.append("")
                    lines.append("原因：搜索虽返回了一些相似内容，但未覆盖关键标识词，结果不可靠。")
                elif final_verify_reason == "low_relevance_semantic_hits":
                    lines.append("")
                    lines.append("原因：搜索结果相关性较弱，未通过校验。")

            else:
                lines.append(f"结果：找到 {len(hits)} 条相关内容。")

            if hits:
                lines.append("")
                lines.append("前3条结果：")
                for i, h in enumerate(hits[:3], start=1):
                    filename = h.get("filename", "")
                    chunk_id = h.get("chunk_id", "")
                    snippet = str(h.get("snippet", "")).strip().replace("\n", " ")
                    if len(snippet) > 80:
                        snippet = snippet[:80] + "..."
                    lines.append(f"{i}. {filename} / {chunk_id} / {snippet}")

            return "\n".join(lines)

        # ===== 3) 多步执行：成功 =====
        if len(state.plan) > 1 and state.status == "done":
            lines = []
            lines.append("任务已完成。")
            lines.append("")
            lines.append("执行过程：")

            for i, (call, res) in enumerate(zip(state.plan, state.step_results), start=1):
                step_id = call.id or f"step{i}"
                status_text = "成功" if res.ok else "失败"
                lines.append(f"{i}. [{step_id}] {call.name}：{status_text}")

            return "\n".join(lines)

        # ===== 4) 多步执行：最终失败，但把原因讲清楚 =====
        if len(state.plan) > 1 and state.status == "failed":
            lines = []
            lines.append("未得到可靠结果。")
            lines.append("")
            lines.append("执行过程：")

            for i, (call, res) in enumerate(zip(state.plan, state.step_results), start=1):
                step_id = call.id or f"step{i}"

                if res.ok:
                    lines.append(f"{i}. [{step_id}] {call.name}：执行成功")
                else:
                    lines.append(f"{i}. [{step_id}] {call.name}：执行失败（{res.error}）")

            # 针对常见场景补一句人话说明
            first_call = state.plan[0].name if state.plan else ""
            first_output = state.step_results[0].output if state.step_results else {}
            first_output = first_output if isinstance(first_output, dict) else {}

            if first_call == "knowledge_rag_answer":
                answer = str(first_output.get("answer", "")).strip()
                if "未在知识库中找到明确答案" in answer:
                    lines.append("")
                    lines.append("原因：知识问答未找到明确答案，补充搜索后结果仍不可靠。")
                else:
                    lines.append("")
                    lines.append("原因：虽然完成了工具执行，但校验阶段认为结果不够可靠。")

            elif first_call in {"knowledge_search", "knowledge_semantic_search"}:
                lines.append("")

                if final_verify_reason == "strong_token_not_covered":
                    lines.append("原因：搜索虽返回了一些相似内容，但未覆盖关键标识词，结果不可靠。")
                elif final_verify_reason == "low_relevance_semantic_hits":
                    lines.append("原因：搜索结果相关性较弱，未通过校验。")
                elif final_verify_reason == "knowledge_search_empty":
                    lines.append("原因：首轮搜索未命中，补充检索后仍未得到可靠结果。")
                elif final_verify_reason == "knowledge_semantic_search_empty":
                    lines.append("原因：补充语义检索后仍未找到有效结果。")
                else:
                    lines.append("原因：虽然搜索返回了内容，但校验阶段认为相关性不足，结果不可靠。")

            else:
                lines.append("")
                lines.append("原因：工具执行虽已完成，但最终校验未通过。")

            return "\n".join(lines)

        # ===== 5) 默认兜底 =====
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
            data["verify_result"] = getattr(state, "verify_result", {})
            data["verify_result_after_retry"] = getattr(state, "verify_result_after_retry", {})

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

            # M4.1
            # for call in state.plan:
            #     try:
            #         out = await self.tool_exec.call(trace_id, call.name, call.args)
            #         state.step_results.append(StepResult(ok=True, output=out))
            #     except Exception as e:
            #         state.step_results.append(StepResult(ok=False, error=str(e)))
            
            # M4.2 multi-step execution loop
            context = {}

            for i, call in enumerate(state.plan, start=1):
                try:
                    resolved_args = self._resolve_args(call.args, context)
                    final_args, rewrite_info = self._rewrite_and_inject_route_args(call.name, resolved_args)

                    self.audit.write(
                        trace_id,
                        "step_resolved",
                        {
                            "step_id": call.id or f"step{i}",
                            "tool": call.name,
                            "raw_args": call.args,
                            "resolved_args": resolved_args,
                            "final_args": final_args,
                            "rewrite_info": rewrite_info,
                        },
                    )

                    out = await self.tool_exec.call(trace_id, call.name, final_args)
                    state.step_results.append(StepResult(ok=True, output=out))

                    context_key = call.id or f"step{i}"
                    context[context_key] = {
                        "tool": call.name,
                        "args": final_args,
                        "output": out,
                        "rewrite_info": rewrite_info,
                    }

                except Exception as e:
                    state.step_results.append(StepResult(ok=False, error=str(e)))

                    context_key = call.id or f"step{i}"
                    context[context_key] = {
                        "tool": call.name,
                        "args": call.args,
                        "output": None,
                        "error": str(e),
                    }

                    # 当前 M4.2 先做“遇错即停”
                    break

            # VERIFY
            state.status = "verifying"
            await self.store.update_task(trace_id, state.status)

            basic_ok = self.verify_basic(state)

            verify_out = verify_state(state)
            state.verify_result = verify_out

            self.audit.write(
                trace_id,
                "verify_result",
                {
                    "basic_ok": basic_ok,
                    "verify_ok": verify_out.get("ok"),
                    "verify_status": verify_out.get("status"),
                    "reason": verify_out.get("reason"),
                    "detail": verify_out.get("detail"),
                    "action": verify_out.get("action"),
                    "metrics": verify_out.get("metrics", {}),
                    "suggested_plan": [
                        c.model_dump() for c in verify_out.get("suggested_plan", [])
                    ],
                },
            )

            verify_status = verify_out.get("status", "fatal")
            action = verify_out.get("action", "fallback")
            suggested_plan = verify_out.get("suggested_plan", []) or []

            if not basic_ok:
                ok = False

            elif verify_status == "pass":
                ok = True

            elif action == "retry" and suggested_plan:
                await self._run_verified_retry(trace_id, state, suggested_plan)

                verify_out_2 = verify_state(state)
                state.verify_result_after_retry = verify_out_2

                self.audit.write(
                    trace_id,
                    "verify_result_after_retry",
                    {
                        "verify_ok": verify_out_2.get("ok"),
                        "verify_status": verify_out_2.get("status"),
                        "reason": verify_out_2.get("reason"),
                        "detail": verify_out_2.get("detail"),
                        "action": verify_out_2.get("action"),
                        "metrics": verify_out_2.get("metrics", {}),
                    },
                )

                ok = (
                    all(r.ok for r in state.step_results)
                    and verify_out_2.get("status") == "pass"
                )

            elif action == "fallback":
                ok = False

            else:
                ok = False

            # REPORT
            state.status = "done" if ok else "failed"
            await self.store.update_task(trace_id, state.status)

            state.final_answer = self.report(state)

            self.audit.write(trace_id, "task_end", {"status": state.status})
            await self.store.update_task(trace_id, state.status, ended=True)
            return state

        except Exception as e:
            state.status = "failed"
            state.final_answer = f"运行失败：{e}"
            self.audit.write(trace_id, "task_crash", {"error": str(e)})
            await self.store.update_task(trace_id, state.status, error=str(e), ended=True)
            return state
