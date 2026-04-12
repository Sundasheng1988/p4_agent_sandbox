# verifier
from __future__ import annotations
from typing import Any, Dict, List, Literal
from app.core.models import TaskState, ToolCall

WEAK_ANSWER_PATTERNS = [
    "未生成回答",
    "未在知识库中找到明确答案",
    "不知道",
    "无法回答",
]

# ===== M4.3-v2 阈值，可后续调参 =====
MIN_SEMANTIC_TOP1_SCORE = 0.30
MIN_SEMANTIC_AVG_TOP3_SCORE = 0.25
MIN_RAG_TOP1_SCORE = 0.30

# ===== verifier 状态 =====
VerifyStatus = Literal["pass", "weak", "insufficient", "fatal"]
VerifyAction = Literal["continue", "retry", "replan", "fallback"]

MAX_VERIFIER_RETRIES = 1


def _is_empty_output(output: Any) -> bool:
    if output is None:
        return True

    if isinstance(output, str):
        return not output.strip()

    if isinstance(output, list):
        return len(output) == 0

    if isinstance(output, dict):
        return len(output) == 0

    return False

# TODO: deprecated, use _classify_weak_answer instead
def _is_weak_answer(answer: str) -> bool:
    text = (answer or "").strip()
    if not text:
        return True

    if len(text) < 6:
        return True

    for p in WEAK_ANSWER_PATTERNS:
        if p in text:
            return True

    return False

def _classify_weak_answer(answer: str) -> Dict[str, Any]:
    text = (answer or "").strip()

    if not text:
        return {
            "is_weak": True,
            "weak_type": "generation_issue",
            "reason": "empty_answer",
        }

    if len(text) < 6:
        return {
            "is_weak": True,
            "weak_type": "generation_issue",
            "reason": "too_short",
        }

    no_evidence_patterns = [
        "未在知识库中找到明确答案",
        "没有足够信息",
        "无法根据上下文判断",
        "上下文不足",
    ]
    for p in no_evidence_patterns:
        if p in text:
            return {
                "is_weak": True,
                "weak_type": "no_evidence",
                "reason": p,
            }

    weak_patterns = [
        "未生成回答",
        "不知道",
        "无法回答",
    ]
    for p in weak_patterns:
        if p in text:
            return {
                "is_weak": True,
                "weak_type": "generation_issue",
                "reason": p,
            }

    return {
        "is_weak": False,
        "weak_type": "",
        "reason": "",
    }


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default

def _make_decision(
    status: VerifyStatus,
    reason: str,
    action: VerifyAction = "continue",
    suggested_plan: List[ToolCall] | None = None,
    detail: str = "",
    metrics: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "ok": status == "pass",
        "status": status,
        "reason": reason,
        "detail": detail,
        "action": action,
        "suggested_plan": suggested_plan or [],
        "metrics": metrics or {},
    }

def _count_retry_steps(state: TaskState) -> int:
    count = 0
    for c in state.plan or []:
        step_id = str(getattr(c, "id", "") or "")
        if step_id.startswith("retry"):
            count += 1
    return count

def _extract_strong_tokens(query: str) -> List[str]:
    import re

    query = (query or "").strip()
    if not query:
        return []

    tokens = re.findall(r"[A-Za-z0-9_\-]{3,}", query)
    tokens = [t.lower() for t in tokens if t.strip()]

    seen = set()
    result = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)

    return result

def _expand_strong_tokens(tokens: List[str]) -> List[str]:
    """
    对强 token 做轻量同义扩展，便于中英术语对齐。
    """
    synonym_map = {
        "planning": ["规划"],
        "perception": ["感知"],
        "localization": ["定位"],
        "prediction": ["预测"],
        "trajectory": ["轨迹"],
        "retrieval": ["检索"],
        "rerank": ["重排"],
        "router": ["路由"],
        "routing": ["路由"],
        "embedding": ["向量"],
        "grasp": ["抓取"],
        "vision": ["视觉"],
        "camera": ["相机"],
        "servo": ["舵机"],
        "robot": ["机器人"],
        "robotics": ["机器人"],
    }

    out: List[str] = []
    seen = set()

    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)

        for x in synonym_map.get(t, []):
            if x not in seen:
                seen.add(x)
                out.append(x)

    return out

def _is_entity_query(query: str) -> bool:
    text = (query or "").strip().lower()
    if not text:
        return False

    entity_markers = [
        "是什么",
        "是谁",
        "什么是",
        "啥是",
        "是什么东西",
        "meaning",
        "define",
        "what is",
        "who is",
    ]

    # 明确带“定义/是什么”这类问法，才判为实体型问题
    if any(m in text for m in entity_markers):
        return True

    return False


def _has_token_coverage(tokens: List[str], hits: List[Dict[str, Any]], top_k: int = 5) -> bool:
    if not tokens:
        return True

    buf: List[str] = []
    for h in hits[:top_k]:
        buf.append(str(h.get("filename", "")))
        buf.append(str(h.get("snippet", "")))

        section_path = h.get("section_path", []) or []
        if isinstance(section_path, list):
            buf.extend([str(x) for x in section_path])

    text = " ".join(buf).lower()
    return any(t in text for t in tokens)


def _semantic_quality(hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not hits:
        return {
            "ok": False,
            "reason": "no_hits",
            "top1_score": 0.0,
            "avg_top3_score": 0.0,
            "hits_count": 0,
        }

    scores = [
        _safe_float(h.get("rerank_score", h.get("score", 0.0)))
        for h in hits
    ]

    top1_score = scores[0]
    top3 = scores[:3]
    avg_top3_score = sum(top3) / len(top3) if top3 else 0.0
    hits_count = len(hits)

    # 单条命中时更严格一点
    if hits_count == 1 and top1_score < 0.35:
        return {
            "ok": False,
            "reason": "single_hit_score_too_low",
            "top1_score": round(top1_score, 6),
            "avg_top3_score": round(avg_top3_score, 6),
            "hits_count": hits_count,
        }

    if top1_score < MIN_SEMANTIC_TOP1_SCORE:
        return {
            "ok": False,
            "reason": "top1_score_too_low",
            "top1_score": round(top1_score, 6),
            "avg_top3_score": round(avg_top3_score, 6),
            "hits_count": hits_count,
        }

    if avg_top3_score < MIN_SEMANTIC_AVG_TOP3_SCORE:
        return {
            "ok": False,
            "reason": "avg_top3_score_too_low",
            "top1_score": round(top1_score, 6),
            "avg_top3_score": round(avg_top3_score, 6),
            "hits_count": hits_count,
        }

    return {
        "ok": True,
        "reason": "semantic_hits_ok",
        "top1_score": round(top1_score, 6),
        "avg_top3_score": round(avg_top3_score, 6),
        "hits_count": hits_count,
    }


def verify_state(state: TaskState) -> Dict[str, Any]:
    """
    返回：
    {
      "ok": bool,
      "status": "pass" | "weak" | "insufficient" | "fatal",
      "reason": str,
      "detail": str,
      "action": "continue" | "retry" | "replan" | "fallback",
      "suggested_plan": [...],
      "metrics": {...},
    }
    """
    if not state.step_results:
        return _make_decision(
            status="fatal",
            reason="no_step_results",
            action="fallback",
        )

    last_call = state.plan[-1] if state.plan else None
    last_res = state.step_results[-1]

    if last_call is None:
        return _make_decision(
            status="fatal",
            reason="no_last_call",
            action="fallback",
        )

    if not last_res.ok:
        return _make_decision(
            status="fatal",
            reason="step_failed",
            action="fallback",
        )

    output = last_res.output

    # 1) knowledge_search：空结果 -> 根据 query 类型决定 retry 还是 fallback
    if last_call.name == "knowledge_search":
        hits = []
        if isinstance(output, dict):
            hits = output.get("hits", []) or []

        if len(hits) == 0:
            query = ""
            if last_call.args:
                query = str(last_call.args.get("query", "")).strip()

            retry_count = _count_retry_steps(state)
            strong_tokens = _expand_strong_tokens(_extract_strong_tokens(query))
            is_entity = _is_entity_query(query)

            # 只要 query 中出现看起来像唯一标识符的强 token（如 abc999 / sdk_v2 / trac-ik），
            # 首轮 search 空结果时直接 fallback，避免无意义 semantic retry
            looks_like_unique_token = any(any(ch.isdigit() for ch in t) or "-" in t or "_" in t for t in strong_tokens)

            if strong_tokens and looks_like_unique_token:
                return _make_decision(
                    status="insufficient",
                    reason="knowledge_search_empty_strong_unique_token",
                    action="fallback",
                    metrics={
                        "retry_count": retry_count,
                        "query": query,
                        "strong_tokens": strong_tokens,
                        "is_entity_query": is_entity,
                        "looks_like_unique_token": looks_like_unique_token,
                    },
                )

            if retry_count >= MAX_VERIFIER_RETRIES:
                return _make_decision(
                    status="insufficient",
                    reason="knowledge_search_empty_retry_limit_reached",
                    action="fallback",
                    metrics={
                        "retry_count": retry_count,
                        "query": query,
                        "strong_tokens": strong_tokens,
                        "is_entity_query": is_entity,
                        "looks_like_unique_token": looks_like_unique_token,
                    },
                )

            suggested: List[ToolCall] = []
            if query:
                suggested.append(
                    ToolCall(
                        id=f"retry{retry_count + 1}",
                        name="knowledge_semantic_search",
                        args={"query": query, "limit": 10},
                    )
                )

            return _make_decision(
                status="insufficient",
                reason="knowledge_search_empty",
                action="retry",
                suggested_plan=suggested,
                metrics={
                    "retry_count": retry_count,
                    "query": query,
                    "strong_tokens": strong_tokens,
                    "is_entity_query": is_entity,
                    "looks_like_unique_token": looks_like_unique_token,
                },
            )

        return _make_decision(
            status="pass",
            reason="knowledge_search_ok",
            action="continue",
            metrics={"hits_count": len(hits)},
        )

    # 2) knowledge_semantic_search：空结果 / 低质量 / token 不覆盖
    if last_call.name == "knowledge_semantic_search":
        hits = []
        query = ""
        if isinstance(output, dict):
            hits = output.get("hits", []) or []
             # 优先用 tool 实际执行后的 query（可能已被 rewrite）
            query = str(output.get("query", "")).strip()

        # 如果 output 里没有，再 fallback 到原始 plan args
        if not query and last_call.args:
            query = str(last_call.args.get("query", "")).strip()

        if len(hits) == 0:
            return _make_decision(
                status="insufficient",
                reason="knowledge_semantic_search_empty",
                action="fallback",
                metrics={"query": query},
            )
        
        strong_tokens = _expand_strong_tokens(_extract_strong_tokens(query))
        token_covered = _has_token_coverage(strong_tokens, hits, top_k=5)
        is_entity = _is_entity_query(query)
        looks_like_unique_token = any(
            any(ch.isdigit() for ch in t) or "-" in t or "_" in t
            for t in strong_tokens
        )

        q = _semantic_quality(hits)
        if not q["ok"]:
            return _make_decision(
                status="insufficient",
                reason="low_relevance_semantic_hits",
                detail=q["reason"],
                action="fallback",
                metrics={
                    "top1_score": q["top1_score"],
                    "avg_top3_score": q["avg_top3_score"],
                    "hits_count": q["hits_count"],
                    "query": query,
                    "strong_tokens": strong_tokens,
                    "token_covered": token_covered,
                    "is_entity_query": is_entity,
                    "looks_like_unique_token": looks_like_unique_token,
                },
            )



        # 对唯一标识符类 token（如 abc999 / sdk_v2 / trac-ik），无论是否实体型问题，
        # 只要 token 完全未覆盖，都直接判失败
        if strong_tokens and not token_covered and looks_like_unique_token:
            return _make_decision(
                status="insufficient",
                reason="strong_unique_token_not_covered",
                action="fallback",
                metrics={
                    "strong_tokens": strong_tokens,
                    "is_entity_query": is_entity,
                    "looks_like_unique_token": looks_like_unique_token,
                    "top1_score": q["top1_score"],
                    "avg_top3_score": q["avg_top3_score"],
                    "hits_count": q["hits_count"],
                    "query": query,
                },
            )

        # 对普通词（如 rabbit / agent），只有在非实体型问题里才严格要求 token 覆盖
        if strong_tokens and not token_covered and not is_entity:
            return _make_decision(
                status="insufficient",
                reason="strong_token_not_covered",
                action="fallback",
                metrics={
                    "strong_tokens": strong_tokens,
                    "is_entity_query": is_entity,
                    "looks_like_unique_token": looks_like_unique_token,
                    "top1_score": q["top1_score"],
                    "avg_top3_score": q["avg_top3_score"],
                    "hits_count": q["hits_count"],
                    "query": query,
                },
            )

        # 如果这一步来自弱 RAG fallback，则进一步保守处理
        if len(state.plan) >= 2 and len(state.step_results) >= 2:
            prev_call = state.plan[-2]
            prev_res = state.step_results[-2]

            if prev_call.name == "knowledge_rag_answer" and prev_res.ok:
                prev_output = prev_res.output if isinstance(prev_res.output, dict) else {}
                prev_answer = str(prev_output.get("answer", "")).strip()
                prev_weak_info = _classify_weak_answer(prev_answer)

                if prev_weak_info["is_weak"]:
                    return _make_decision(
                        status="insufficient",
                        reason="semantic_fallback_after_weak_rag",
                        action="fallback",
                        detail=prev_weak_info["reason"],
                        metrics={
                            "top1_score": q["top1_score"],
                            "avg_top3_score": q["avg_top3_score"],
                            "hits_count": q["hits_count"],
                            "query": query,
                            "prev_weak_type": prev_weak_info["weak_type"],
                        },
                    )

        return _make_decision(
            status="pass",
            reason="knowledge_semantic_search_ok",
            action="continue",
            metrics={
                "top1_score": q["top1_score"],
                "avg_top3_score": q["avg_top3_score"],
                "hits_count": q["hits_count"],
                "query": query,
                "strong_tokens": strong_tokens,
                "token_covered": token_covered,
                "is_entity_query": is_entity,
                "looks_like_unique_token": looks_like_unique_token,
            },
        )

    # 3) knowledge_rag_answer：弱回答 -> 区分“证据不足”还是“生成问题”
    if last_call.name == "knowledge_rag_answer":
        answer = ""
        hits = []
        question = ""

        if isinstance(output, dict):
            answer = str(output.get("answer", "")).strip()
            hits = output.get("hits", []) or []
            # 优先用 tool 实际执行后的 question（可能已被 rewrite）
            question = str(output.get("question", "")).strip()

        if not question and last_call.args:
            question = str(last_call.args.get("question", "")).strip()

        weak_info = _classify_weak_answer(answer)

        if weak_info["is_weak"]:
            retry_count = _count_retry_steps(state)

            # 如果是“证据不足型失败”，直接 fallback，不再 retry semantic
            if weak_info["weak_type"] == "no_evidence":
                return _make_decision(
                    status="insufficient",
                    reason="knowledge_rag_no_answer",
                    action="fallback",
                    detail=weak_info["reason"],
                    metrics={
                        "retry_count": retry_count,
                        "question": question,
                        "weak_type": weak_info["weak_type"],
                        "hits_count": len(hits),
                        "answer_preview": answer[:80],
                    },
                )

            # 只有“生成问题型失败”才允许 retry
            if retry_count >= MAX_VERIFIER_RETRIES:
                return _make_decision(
                    status="insufficient",
                    reason="knowledge_rag_answer_weak_retry_limit_reached",
                    action="fallback",
                    detail=weak_info["reason"],
                    metrics={
                        "retry_count": retry_count,
                        "question": question,
                        "weak_type": weak_info["weak_type"],
                        "hits_count": len(hits),
                    },
                )

            suggested: List[ToolCall] = []
            if question:
                suggested.append(
                    ToolCall(
                        id=f"retry{retry_count + 1}",
                        name="knowledge_semantic_search",
                        args={"query": question, "limit": 10},
                    )
                )

            return _make_decision(
                status="weak",
                reason="knowledge_rag_answer_weak",
                action="retry",
                suggested_plan=suggested,
                detail=weak_info["reason"],
                metrics={
                    "retry_count": retry_count,
                    "question": question,
                    "weak_type": weak_info["weak_type"],
                    "hits_count": len(hits),
                },
            )

        return _make_decision(
            status="pass",
            reason="knowledge_rag_answer_ok",
            action="continue",
            metrics={"hits_count": len(hits), "question": question},
        )
    
    # 4) 通用空输出
    if _is_empty_output(output):
        return _make_decision(
            status="insufficient",
            reason="empty_output",
            action="fallback",
        )

    return _make_decision(
        status="pass",
        reason="ok",
        action="continue",
    )
