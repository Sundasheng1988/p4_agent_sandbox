from __future__ import annotations

from typing import Any, Dict, List


def _pick_text(hit: Dict[str, Any]) -> str:
    text = (hit.get("full_text") or "").strip()
    if text:
        return text
    return (hit.get("snippet") or "").strip()


def _normalize_text(s: str) -> str:
    return (s or "").strip().lower()


def _detect_query_type(query: str) -> str:
    q = _normalize_text(query)

    compare_markers = ["区别", "不同", "对比"]
    process_markers = ["流程", "步骤", "怎么做", "顺序"]
    architecture_markers = ["架构", "模块", "节点", "组成", "系统"]
    relation_markers = ["关系", "联系", "作用"]

    if any(m in q for m in compare_markers):
        return "compare"
    if any(m in q for m in process_markers):
        return "process"
    if any(m in q for m in architecture_markers):
        return "architecture"
    if any(m in q for m in relation_markers):
        return "relation"

    return "general"


def _is_noise_hit(hit: Dict[str, Any], query_type: str) -> bool:
    section_title = _normalize_text(str(hit.get("section_title") or ""))
    section_path = _normalize_text(" / ".join(hit.get("section_path") or []))
    text = _normalize_text(_pick_text(hit))

    if not text:
        return True

    if len(text) < 30:
        return True

    # 强噪声
    if "keywords" in section_title or text.startswith("keywords"):
        return True

    # 明显问题/故障类，通常不该默认进主 context
    noisy_markers = [
        "failure",
        "error",
        "common issues",
        "issues",
        "troubleshooting",
    ]
    if any(m in section_title for m in noisy_markers):
        return True
    if any(m in section_path for m in noisy_markers):
        return True

    # 改进建议类，一般优先级较低
    if "improve" in section_title and query_type not in ("general",):
        return True

    return False


def _base_score(hit: Dict[str, Any]) -> float:
    try:
        return float(hit.get("score", 0.0))
    except Exception:
        return 0.0


def _score_hit(hit: Dict[str, Any], query_type: str) -> float:
    score = _base_score(hit)

    section_title = _normalize_text(str(hit.get("section_title") or ""))
    section_path = _normalize_text(" / ".join(hit.get("section_path") or []))
    text = _normalize_text(_pick_text(hit))

    boost = 0.0

    # -------- 通用 boost --------
    if "system architecture" in section_title:
        boost += 0.35
    if "overview" in section_title:
        boost += 0.18
    if section_title.endswith("_node") or "_node" in section_title:
        boost += 0.10

    # 数据流信息很有价值
    if "data flow" in text:
        boost += 0.12

    # -------- 按问题类型加权 --------
    if query_type == "process":
        if "step" in section_title:
            boost += 0.28
        if "pipeline" in section_title or "grasp pipeline" in section_path:
            boost += 0.20
        if "motion execution" in section_title:
            boost += 0.12
        if "system architecture" in section_title:
            boost += 0.08  # 流程题里 architecture 仍有帮助

    elif query_type == "architecture":
        if "system architecture" in section_title:
            boost += 0.40
        if section_title.endswith("_node") or "_node" in section_title:
            boost += 0.18
        if "overview" in section_title:
            boost += 0.12
        if "step" in section_title:
            boost -= 0.05

    elif query_type == "compare":
        # 对比题：既需要架构类，也需要流程类
        if "system architecture" in section_title:
            boost += 0.38
        if "step" in section_title:
            boost += 0.24
        if section_title.endswith("_node") or "_node" in section_title:
            boost += 0.14
        if "overview" in section_title:
            boost += 0.10

    elif query_type == "relation":
        # 关系题：节点和架构通常都很重要
        if "system architecture" in section_title:
            boost += 0.28
        if section_title.endswith("_node") or "_node" in section_title:
            boost += 0.22
        if "overview" in section_title:
            boost += 0.06

    # -------- 轻惩罚 --------
    if "servo control" in section_title and query_type in ("compare", "architecture"):
        boost += 0.03

    if "step" in section_title and query_type == "architecture":
        boost -= 0.03

    return round(score + boost, 6)


def _rerank_hits(hits: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    query_type = _detect_query_type(query)

    ranked: List[Dict[str, Any]] = []

    for hit in hits:
        if _is_noise_hit(hit, query_type=query_type):
            continue

        row = dict(hit)
        row["_context_score"] = _score_hit(hit, query_type=query_type)
        ranked.append(row)

    ranked.sort(
        key=lambda x: (
            float(x.get("_context_score", 0.0)),
            float(x.get("score", 0.0)),
        ),
        reverse=True,
    )
    return ranked


def build_context(
    hits: List[Dict[str, Any]],
    max_chars: int = 4000,
    query: str = "",
) -> str:
    ranked_hits = _rerank_hits(hits, query=query)

    parts: List[str] = []
    total = 0
    kept_index = 0

    for hit in ranked_hits:
        text = _pick_text(hit)
        if not text:
            continue

        kept_index += 1

        filename = hit.get("filename", "")
        chunk_id = hit.get("chunk_id", "")
        score = hit.get("score", 0)
        section_title = hit.get("section_title", "")
        context_score = hit.get("_context_score", 0)

        header = (
            f"[{kept_index}] "
            f"file={filename} "
            f"chunk={chunk_id} "
            f"score={score} "
            f"context_score={context_score}"
        )

        if section_title:
            header += f" section={section_title}"

        block = f"{header}\n{text}"

        if total + len(block) > max_chars:
            break

        parts.append(block)
        total += len(block) + 2

    return "\n\n".join(parts)