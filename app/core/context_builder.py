# context_builder
from __future__ import annotations

from typing import Any, Dict, List, Tuple
import re


def _pick_text(hit: Dict[str, Any]) -> str:
    text = (hit.get("full_text") or "").strip()
    if text:
        return text
    return (hit.get("snippet") or "").strip()


def _normalize_text(s: str) -> str:
    return (s or "").strip().lower()

def _get_metadata(hit: Dict[str, Any]) -> Dict[str, Any]:
    md = hit.get("metadata")
    return md if isinstance(md, dict) else {}


def _get_chunk_type(hit: Dict[str, Any]) -> str:
    md = _get_metadata(hit)
    return str(
        hit.get("chunk_type")
        or md.get("chunk_type")
        or md.get("kind")
        or ""
    )


def _is_table_row_hit(hit: Dict[str, Any]) -> bool:
    return _get_chunk_type(hit) == "table_row"


def _detect_query_type(query: str) -> str:
    q = _normalize_text(query)

    compare_markers = ["区别", "不同", "对比"]
    process_markers = ["流程", "步骤", "怎么做", "顺序", "如何", "怎么"]
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
    section_title = _normalize_text(
        str(hit.get("section_title") or hit.get("section") or "")
    )
    section_path = _normalize_text(" / ".join(hit.get("section_path") or []))
    text = _normalize_text(_pick_text(hit))

    if not text:
        return True

    # 问题类/测试类内容，短文本也可能是有效证据，不能直接过滤
    evidence_markers = [
        "问题", "风险", "缺失", "未", "无法", "不稳定", "不足",
        "hallucination", "evidence binding", "grounded",
    ]
    if any(m in section_title for m in evidence_markers) or any(m in text for m in evidence_markers):
        return False

    if len(text) < 30:
        return True

    if "keywords" in section_title or text.startswith("keywords"):
        return True

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
    intent_score = float(hit.get("intent_match_score", 0) or 0)

    section_title = _normalize_text(
        str(hit.get("section_title") or hit.get("section") or "")
    )
    section_path = _normalize_text(" / ".join(hit.get("section_path") or []))
    text = _normalize_text(_pick_text(hit))

    boost = 0.0
    # 结构化表格命中优先进入上下文
    if intent_score > 0:
        boost += intent_score

    # -------- 通用 boost --------
    if "system architecture" in section_title:
        boost += 0.35
    if "overview" in section_title:
        boost += 0.18
    if section_title.endswith("_node") or "_node" in section_title:
        boost += 0.10

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
            boost += 0.08

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
        if "system architecture" in section_title:
            boost += 0.38
        if "step" in section_title:
            boost += 0.24
        if section_title.endswith("_node") or "_node" in section_title:
            boost += 0.14
        if "overview" in section_title:
            boost += 0.10

    elif query_type == "relation":
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


# =========================================================
# M4.5.4.1 / M4.5.4.3 / M4.5.4.4
# Ordering + Step-aware + Section Grouping
# =========================================================
def _group_key(hit: Dict[str, Any]) -> Tuple[str, str]:
    filename = str(hit.get("filename") or "")
    section_path = hit.get("section_path") or []
    if isinstance(section_path, list) and section_path:
        parent_path = section_path[:-1] if len(section_path) > 1 else section_path
        return (filename, " > ".join(str(x) for x in parent_path))

    section = str(hit.get("section_title") or hit.get("section") or "")
    return (filename, section)


def _extract_step_no(hit: Dict[str, Any]) -> int | None:
    """
    从 section_title / section 中提取 Step 序号
    例如：
    - Step 1: Object Detection -> 1
    - Step 2: Coordinate Transformation -> 2
    """
    section_title = str(hit.get("section_title") or hit.get("section") or "").strip()
    if not section_title:
        return None

    m = re.match(r"step\s+(\d+)", section_title.strip(), flags=re.IGNORECASE)
    if not m:
        return None

    try:
        return int(m.group(1))
    except Exception:
        return None


def _is_step_hit(hit: Dict[str, Any]) -> bool:
    return _extract_step_no(hit) is not None


def _section_group_priority(hit: Dict[str, Any], query_type: str) -> int:
    """
    数值越小，优先级越高
    """
    section_title = _normalize_text(
        str(hit.get("section_title") or hit.get("section") or "")
    )

    step_no = _extract_step_no(hit)

    if query_type == "process":
        if step_no is not None:
            return 0
        if "system architecture" in section_title:
            return 1
        if section_title.endswith("_node") or "_node" in section_title:
            return 2
        if "servo control" in section_title:
            return 3
        return 4

    if query_type == "relation":
        if section_title.endswith("_node") or "_node" in section_title:
            return 0
        if "system architecture" in section_title:
            return 1
        if step_no is not None:
            return 2
        return 3

    if query_type == "architecture":
        if "system architecture" in section_title:
            return 0
        if section_title.endswith("_node") or "_node" in section_title:
            return 1
        if step_no is not None:
            return 2
        return 3

    if query_type == "compare":
        if "system architecture" in section_title:
            return 0
        if step_no is not None:
            return 1
        if section_title.endswith("_node") or "_node" in section_title:
            return 2
        return 3

    return 9


def _order_hits_for_context(hits: List[Dict[str, Any]], query: str = "") -> List[Dict[str, Any]]:
    """
    目标：
    - 保留 rerank 的大方向
    - process 问题优先按 Step 顺序组织
    - 增加 section grouping，让主干 section 优先进入 context
    """
    if not hits:
        return []

    query_type = _detect_query_type(query)

    enriched_hits: List[Dict[str, Any]] = []
    for hit in hits:
        row = dict(hit)
        row["_step_no"] = _extract_step_no(hit)
        row["_section_group_priority"] = _section_group_priority(hit, query_type=query_type)
        enriched_hits.append(row)

    # process：先 section group，再 step，再 chunk，再 score
    if query_type == "process":
        return sorted(
            enriched_hits,
            key=lambda x: (
                int(x.get("_section_group_priority", 9)),
                int(x.get("_step_no") or 9999),
                x.get("chunk_index") is None,
                int(x.get("chunk_index") or 0),
                -float(x.get("_context_score", 0.0)),
            ),
        )

    # relation / architecture / compare：
    # 先按 section group，再按 context_score，再按 chunk_index
    if query_type in ("relation", "architecture", "compare"):
        return sorted(
            enriched_hits,
            key=lambda x: (
                int(x.get("_section_group_priority", 9)),
                -float(x.get("_context_score", 0.0)),
                x.get("chunk_index") is None,
                int(x.get("chunk_index") or 0),
            ),
        )

        # general：
    # 如果是表格行，优先按 context_score 排序，不能再按 chunk_index 把早页噪音排前面
    table_hits = [h for h in enriched_hits if _is_table_row_hit(h)]
    normal_hits = [h for h in enriched_hits if not _is_table_row_hit(h)]

    table_hits_sorted = sorted(
        table_hits,
        key=lambda x: (
            -float(x.get("_context_score", 0.0)),
            -float(x.get("score", 0.0)),
            x.get("chunk_index") is None,
            int(x.get("chunk_index") or 0),
        ),
    )

    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    group_best_score: Dict[Tuple[str, str], float] = {}

    for hit in normal_hits:
        key = _group_key(hit)
        grouped.setdefault(key, []).append(hit)

        score = float(hit.get("_context_score", 0.0))
        if key not in group_best_score or score > group_best_score[key]:
            group_best_score[key] = score

    ordered_group_keys = sorted(
        grouped.keys(),
        key=lambda k: group_best_score.get(k, 0.0),
        reverse=True,
    )

    ordered_normal_hits: List[Dict[str, Any]] = []
    for key in ordered_group_keys:
        group_hits = grouped[key]
        group_hits_sorted = sorted(
            group_hits,
            key=lambda x: (
                -float(x.get("_context_score", 0.0)),
                x.get("chunk_index") is None,
                int(x.get("chunk_index") or 0),
            ),
        )
        ordered_normal_hits.extend(group_hits_sorted)

    return table_hits_sorted + ordered_normal_hits


# =========================================================
# M4.5.4.2 Adjacent Chunk Merge
# =========================================================
def _can_merge_adjacent(prev_hit: Dict[str, Any], cur_hit: Dict[str, Any]) -> bool:
    # 表格行是原子证据，不允许和相邻行合并
    if _is_table_row_hit(prev_hit) or _is_table_row_hit(cur_hit):
        return False
    
    if str(prev_hit.get("filename") or "") != str(cur_hit.get("filename") or ""):
        return False

    prev_idx = prev_hit.get("chunk_index")
    cur_idx = cur_hit.get("chunk_index")

    if prev_idx is None or cur_idx is None:
        return False

    try:
        prev_idx = int(prev_idx)
        cur_idx = int(cur_idx)
    except Exception:
        return False

    if cur_idx != prev_idx + 1:
        return False

    prev_section = str(prev_hit.get("section_title") or prev_hit.get("section") or "")
    cur_section = str(cur_hit.get("section_title") or cur_hit.get("section") or "")

    if prev_section and cur_section and prev_section != cur_section:
        return False

    return True


def _merge_two_hits(prev_hit: Dict[str, Any], cur_hit: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(prev_hit)

    prev_text = _pick_text(prev_hit)
    cur_text = _pick_text(cur_hit)

    if cur_text and cur_text not in prev_text:
        merged["full_text"] = f"{prev_text}\n\n{cur_text}".strip()

    merged["chunk_id"] = f"{prev_hit.get('chunk_id')}+{cur_hit.get('chunk_id')}"
    merged["chunk_index_end"] = cur_hit.get("chunk_index")

    merged["_context_score"] = max(
        float(prev_hit.get("_context_score", 0.0)),
        float(cur_hit.get("_context_score", 0.0)),
    )
    merged["score"] = max(
        float(prev_hit.get("score", 0.0)),
        float(cur_hit.get("score", 0.0)),
    )

    return merged


def _merge_adjacent_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not hits:
        return []

    merged_hits: List[Dict[str, Any]] = []
    current = dict(hits[0])

    for nxt in hits[1:]:
        if _can_merge_adjacent(current, nxt):
            current = _merge_two_hits(current, nxt)
        else:
            merged_hits.append(current)
            current = dict(nxt)

    merged_hits.append(current)
    return merged_hits


# =========================================================
# M4.5.4.5 Multi-section Aggregation
# =========================================================
def _merge_step_hits(prev_hit: Dict[str, Any], cur_hit: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(prev_hit)

    prev_text = _pick_text(prev_hit)
    cur_text = _pick_text(cur_hit)

    if cur_text and cur_text not in prev_text:
        merged["full_text"] = f"{prev_text}\n\n{cur_text}".strip()

    merged["chunk_id"] = f"{prev_hit.get('chunk_id')}+{cur_hit.get('chunk_id')}"
    merged["chunk_index_end"] = cur_hit.get("chunk_index")

    prev_section = str(prev_hit.get("section_title") or prev_hit.get("section") or "")
    cur_section = str(cur_hit.get("section_title") or cur_hit.get("section") or "")
    merged["section_title"] = f"{prev_section} -> {cur_section}".strip(" ->")

    merged["_context_score"] = max(
        float(prev_hit.get("_context_score", 0.0)),
        float(cur_hit.get("_context_score", 0.0)),
    )
    merged["score"] = max(
        float(prev_hit.get("score", 0.0)),
        float(cur_hit.get("score", 0.0)),
    )

    merged["_step_no"] = prev_hit.get("_step_no")
    return merged


def _aggregate_process_sections(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    对 process 问题进行 Multi-section Aggregation：
    - 找出同文件中的 Step section
    - 尽量按 Step 序号聚合
    - 当前最小版本：只聚合 hits 中已经命中的 step
    - 不跨文件聚合
    """
    if not hits:
        return []

    step_hits = [h for h in hits if _is_step_hit(h)]
    non_step_hits = [h for h in hits if not _is_step_hit(h)]

    if not step_hits:
        return hits

    by_file: Dict[str, List[Dict[str, Any]]] = {}
    for hit in step_hits:
        filename = str(hit.get("filename") or "")
        by_file.setdefault(filename, []).append(hit)

    aggregated_step_hits: List[Dict[str, Any]] = []

    for filename, file_hits in by_file.items():
        file_hits_sorted = sorted(
            file_hits,
            key=lambda x: (
                int(x.get("_step_no") or 9999),
                x.get("chunk_index") is None,
                int(x.get("chunk_index") or 0),
            ),
        )

        current = dict(file_hits_sorted[0])

        for nxt in file_hits_sorted[1:]:
            cur_step = current.get("_step_no")
            nxt_step = nxt.get("_step_no")

            try:
                cur_step = int(cur_step) if cur_step is not None else None
                nxt_step = int(nxt_step) if nxt_step is not None else None
            except Exception:
                cur_step = None
                nxt_step = None

            if cur_step is not None and nxt_step is not None and nxt_step == cur_step + 1:
                current = _merge_step_hits(current, nxt)
            else:
                aggregated_step_hits.append(current)
                current = dict(nxt)

        aggregated_step_hits.append(current)

    return aggregated_step_hits + non_step_hits


def build_context(
    hits: List[Dict[str, Any]],
    max_chars: int = 4000,
    query: str = "",
) -> str:
    ranked_hits = _rerank_hits(hits, query=query)
    ordered_hits = _order_hits_for_context(ranked_hits, query=query)
    merged_hits = _merge_adjacent_hits(ordered_hits)

    query_type = _detect_query_type(query)
    if query_type == "process":
        final_hits = _aggregate_process_sections(merged_hits)
    else:
        final_hits = merged_hits

    parts: List[str] = []
    total = 0
    kept_index = 0

    for hit in final_hits:
        text = _pick_text(hit)
        if not text:
            continue

        kept_index += 1

        filename = hit.get("filename", "")
        chunk_id = hit.get("chunk_id", "")
        score = hit.get("score", 0)
        section_title = hit.get("section_title") or hit.get("section") or ""
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