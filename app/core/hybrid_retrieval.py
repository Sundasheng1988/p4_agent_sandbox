# hybrid_retrieval
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.plugins.tools.knowledge_search import _handler as keyword_search_handler
from app.plugins.tools.knowledge_semantic_search import _handler as semantic_search_handler


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe_key(hit: Dict[str, Any]) -> Tuple[str, str]:
    return str(hit.get("file_id", "")), str(hit.get("chunk_id", ""))


def _norm_text(v: Any) -> str:
    return str(v or "").strip().lower()


def _norm_compact(v: Any) -> str:
    return "".join(str(v or "").strip().lower().split())


def _match_soft(value: Any, expected: str | None) -> bool:
    if not expected:
        return True
    v = _norm_text(value)
    e = _norm_text(expected)
    return bool(v) and (e in v or v in e)


def _load_chunk_by_id(ctx, file_id: str, chunk_id: str) -> Dict[str, Any]:
    if not file_id or not chunk_id:
        return {}

    chunk_path = Path(ctx.sandbox_root) / "artifacts" / "chunks" / f"{file_id}.chunks.json"
    if not chunk_path.exists():
        return {}

    try:
        rec = _load_json(chunk_path)
    except Exception:
        return {}

    for c in rec.get("chunks", []) or []:
        if c.get("chunk_id") == chunk_id:
            return c if isinstance(c, dict) else {}

    return {}


def _enrich_hit_from_chunk_store(ctx, hit: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(hit)

    chunk = _load_chunk_by_id(
        ctx,
        file_id=str(row.get("file_id", "")),
        chunk_id=str(row.get("chunk_id", "")),
    )

    if not chunk:
        return row

    if not row.get("full_text"):
        row["full_text"] = (chunk.get("text") or chunk.get("content") or "").strip()

    if not row.get("metadata") and isinstance(chunk.get("metadata"), dict):
        row["metadata"] = chunk.get("metadata")

    for k in [
        "page",
        "table",
        "row",
        "domain",
        "file_type",
        "source",
        "chunk_type",
        "row_entity",
        "fields",

        # document structure metadata
        "section_id",
        "section_title",
        "section_path",
        "section_type",
        "financial_topic",
        "section_page",
        "section_start",
        "section_end",
    ]:
        if k not in row and k in chunk:
            row[k] = chunk.get(k)

    return row


def _pick_text(hit: Dict[str, Any]) -> str:
    return str(
        hit.get("full_text")
        or hit.get("text")
        or hit.get("content")
        or hit.get("snippet")
        or ""
    )


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


def _get_row_entity(hit: Dict[str, Any]) -> str:
    md = _get_metadata(hit)
    return str(
        hit.get("row_entity")
        or md.get("row_entity")
        or md.get("entity")
        or md.get("metric")
        or ""
    )


def _get_fields(hit: Dict[str, Any]) -> Dict[str, Any]:
    md = _get_metadata(hit)

    fields = hit.get("fields")
    if isinstance(fields, dict):
        return fields

    fields = md.get("fields")
    if isinstance(fields, dict):
        return fields

    row_data = md.get("row_data")
    if isinstance(row_data, dict):
        return row_data

    return {}

def _get_section_type(hit: Dict[str, Any]) -> str:
    md = _get_metadata(hit)
    return str(
        hit.get("section_type")
        or md.get("section_type")
        or ""
    ).strip()


def _get_financial_topics(hit: Dict[str, Any]) -> List[str]:
    md = _get_metadata(hit)

    value = hit.get("financial_topic")
    if value is None:
        value = md.get("financial_topic")

    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    if isinstance(value, str) and value.strip():
        return [value.strip()]

    return []


def _semantic_intent_score(hit: Dict[str, Any], semantic_intent: Dict[str, Any] | None) -> int:
    """
    通用结构化意图 boost：
    - 不写死财报
    - 只使用通用概念：table_row / row_entity / column_field / fields
    """
    if not isinstance(semantic_intent, dict) or not semantic_intent:
        return 0

    wants_table = bool(semantic_intent.get("wants_table"))
    expected_chunk_type = str(semantic_intent.get("expected_chunk_type") or "").strip()
    row_entity = str(semantic_intent.get("row_entity") or "").strip()
    column_field = str(semantic_intent.get("column_field") or "").strip()

    if not wants_table and not expected_chunk_type and not row_entity and not column_field:
        return 0

    score = 0

    text = _pick_text(hit)
    compact_text = _norm_compact(text)

    chunk_type = _get_chunk_type(hit)
    row_value = _get_row_entity(hit)
    fields = _get_fields(hit)

    compact_row = _norm_compact(row_value)
    compact_expected_row = _norm_compact(row_entity)
    compact_expected_col = _norm_compact(column_field)

    field_keys = list(fields.keys())
    compact_field_keys = [_norm_compact(k) for k in field_keys]

    # 1. 用户问题明显在问表格，table_row 优先
    if wants_table:
        if chunk_type == "table_row":
            score += 100

    # 2. expected_chunk_type 精确匹配
    if expected_chunk_type:
        if chunk_type == expected_chunk_type:
            score += 120

    # 3. 行实体匹配，例如：应收账款 / 货币资金 / 注册地址所在行等
    row_matched = False
    if row_entity:
        if compact_expected_row and compact_expected_row == compact_row:
            row_matched = True
            score += 180
        elif compact_expected_row and compact_expected_row in compact_row:
            row_matched = True
            score += 140
        elif compact_expected_row and compact_expected_row in compact_text:
            row_matched = True
            score += 80

    # 4. 列字段匹配，例如：重大变动说明 / 2025年末-金额 / 注册地址
    col_matched = False
    if column_field:
        for ck in compact_field_keys:
            if compact_expected_col and (compact_expected_col == ck or compact_expected_col in ck or ck in compact_expected_col):
                col_matched = True
                score += 160
                break

        if not col_matched and compact_expected_col and compact_expected_col in compact_text:
            col_matched = True
            score += 80

    # 5. 行列同时命中，说明这是强答案候选
    if row_matched and col_matched:
        score += 260

    # 6. 如果 fields 中确实有对应列且值非空，再加分
    if column_field and fields:
        for k, v in fields.items():
            ck = _norm_compact(k)
            cv = str(v or "").strip()
            if compact_expected_col and (compact_expected_col == ck or compact_expected_col in ck or ck in compact_expected_col):
                if cv:
                    score += 80
                break

    return score


def _apply_semantic_intent_boost(
    hits: List[Dict[str, Any]],
    semantic_intent: Dict[str, Any] | None,
) -> List[Dict[str, Any]]:
    if not hits:
        return hits

    out = []
    for hit in hits:
        row = dict(hit)
        intent_score = _semantic_intent_score(row, semantic_intent)
        row["intent_match_score"] = intent_score
        out.append(row)

    out.sort(
        key=lambda x: (
            int(x.get("intent_match_score", 0)),
            int(x.get("multi_query_hit_count", 1)),
            float(x.get("rrf_score", 0.0)),
            float(x.get("rerank_score", x.get("score", 0.0))),
            float(x.get("score", 0.0)),
        ),
        reverse=True,
    )
    return out


def _hit_matches_constraints(
    hit: Dict[str, Any],
    *,
    filename: str | None = None,
    doc_role: str | None = None,
    section_title: str | None = None,
    section_date: str | None = None,
) -> bool:
    if filename:
        if _norm_text(hit.get("filename")) != _norm_text(filename):
            return False

    if doc_role:
        hit_doc_role = _norm_text(hit.get("doc_role"))
        hit_filename = _norm_text(hit.get("filename"))

        if hit_doc_role:
            if hit_doc_role != _norm_text(doc_role):
                return False
        else:
            if doc_role == "roadmap" and "roadmap" not in hit_filename:
                return False
            if doc_role == "dev_log" and "dev_log" not in hit_filename and "dev log" not in hit_filename:
                return False

    if section_date:
        hit_section_date = _norm_text(hit.get("section_date"))
        hit_section_title = _norm_text(hit.get("section_title"))

        if hit_section_date:
            if hit_section_date != _norm_text(section_date):
                return False
        else:
            if hit_section_title != _norm_text(section_date):
                return False

    if section_title:
        title = hit.get("section_title", "")
        path = hit.get("section_path", []) or []
        path_text = " > ".join([str(x) for x in path]) if isinstance(path, list) else str(path)

        if not (_match_soft(title, section_title) or _match_soft(path_text, section_title)):
            return False

    return True


def _filter_hits_by_constraints(
    hits: List[Dict[str, Any]],
    *,
    filename: str | None = None,
    doc_role: str | None = None,
    section_title: str | None = None,
    section_date: str | None = None,
) -> List[Dict[str, Any]]:
    if not any([filename, doc_role, section_title, section_date]):
        return hits

    return [
        h for h in hits
        if _hit_matches_constraints(
            h,
            filename=filename,
            doc_role=doc_role,
            section_title=section_title,
            section_date=section_date,
        )
    ]

def _hit_matches_section_filters(
    hit: Dict[str, Any],
    *,
    section_type: str | None = None,
    financial_topic: str | None = None,
) -> bool:
    if section_type:
        hit_section_type = _get_section_type(hit)
        if hit_section_type != section_type:
            return False

    if financial_topic:
        topics = _get_financial_topics(hit)
        if financial_topic not in topics:
            return False

    return True


def _filter_hits_by_section_filters(
    hits: List[Dict[str, Any]],
    *,
    section_type: str | None = None,
    financial_topic: str | None = None,
) -> List[Dict[str, Any]]:
    if not section_type and not financial_topic:
        return hits

    return [
        h for h in hits
        if _hit_matches_section_filters(
            h,
            section_type=section_type,
            financial_topic=financial_topic,
        )
    ]

def rrf_fuse(
    keyword_hits: List[Dict[str, Any]],
    semantic_hits: List[Dict[str, Any]],
    k: int = 60,
) -> List[Dict[str, Any]]:
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    scores: Dict[Tuple[str, str], float] = {}

    for rank, hit in enumerate(keyword_hits, start=1):
        key = _dedupe_key(hit)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

        if key not in merged:
            merged[key] = dict(hit)
            merged[key]["from_keyword"] = True
            merged[key]["from_semantic"] = False
        else:
            merged[key]["from_keyword"] = True

    for rank, hit in enumerate(semantic_hits, start=1):
        key = _dedupe_key(hit)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)

        if key not in merged:
            merged[key] = dict(hit)
            merged[key]["from_keyword"] = False
            merged[key]["from_semantic"] = True
        else:
            merged[key]["from_semantic"] = True
            for field in [
                "rerank_score",
                "rerank_bonus",
                "section_id",
                "section_title",
                "heading_level",
                "section_path",
                "section_type",
                "financial_topic",
                "section_page",
                "section_start",
                "section_end",
                "start",
                "end",
                "metadata",
                "chunk_type",
                "row_entity",
                "fields",
            ]:
                if field in hit and field not in merged[key]:
                    merged[key][field] = hit[field]

    out: List[Dict[str, Any]] = []
    for key, hit in merged.items():
        row = dict(hit)
        row["rrf_score"] = round(scores[key], 8)
        out.append(row)

    out.sort(
        key=lambda x: (
            float(x.get("rrf_score", 0.0)),
            float(x.get("rerank_score", x.get("score", 0.0))),
            float(x.get("score", 0.0)),
        ),
        reverse=True,
    )
    return out


async def hybrid_retrieve(
    ctx,
    *,
    query: str,
    limit: int = 10,
    domains: list[str] | None = None,
    file_type: str | None = None,
    source: str | None = None,
    filename: str | None = None,
    doc_role: str | None = None,
    section_title: str | None = None,
    section_date: str | None = None,
    section_type: str | None = None,
    financial_topic: str | None = None,
    # ✅ 新增这两行
    file_id: str | None = None,
    semantic_intent: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 50))
    inner_limit = max(1, min(max(limit * 2, 10), 50))
    keyword_out = await keyword_search_handler(
        ctx,
        {
            "query": query,
            "limit": inner_limit,
            "mode": "text",
            "domains": domains,
            "file_type": file_type,
            "source": source,
            # 👇 加这个
            "file_id": file_id,
        },
    )

    semantic_out = await semantic_search_handler(
        ctx,
        {
            "query": query,
            "limit": inner_limit,
            "domains": domains,
            "file_type": file_type,
            "source": source,
            # 👇 加这个
            "file_id": file_id,
        },
    )

    keyword_hits = keyword_out.get("hits", []) if isinstance(keyword_out, dict) else []
    semantic_hits = semantic_out.get("hits", []) if isinstance(semantic_out, dict) else []

    all_fused = rrf_fuse(keyword_hits, semantic_hits)

    # ✅ 硬过滤：只保留指定文件的 chunk
    if file_id:
        all_fused = [
            h for h in all_fused
            if str(h.get("file_id") or "") == str(file_id)
        ]
    
    # 关键：从 chunks.json 补全 full_text / metadata
    all_fused = [_enrich_hit_from_chunk_store(ctx, h) for h in all_fused]

    all_fused = _filter_hits_by_constraints(
        all_fused,
        filename=filename,
        doc_role=doc_role,
        section_title=section_title,
        section_date=section_date,
    )
        # 关键：按 document structure 过滤
    all_fused = _filter_hits_by_section_filters(
        all_fused,
        section_type=section_type,
        financial_topic=financial_topic,
    )

    # 关键：根据 Query Understanding 的结构化意图重排
    all_fused = _apply_semantic_intent_boost(
        all_fused,
        semantic_intent=semantic_intent,
    )

    fused = all_fused[:limit]

    filtered_file_count = None
    if isinstance(semantic_out, dict):
        filtered_file_count = semantic_out.get("filtered_file_count")

    return {
        "ok": True,
        "query": query,
        "limit": limit,
        "domains": domains,
        "file_type": file_type,
        "source": source,
        "file_id": file_id,
        "hits": fused,
        "hits_total": len(all_fused),
        "keyword_hits_count": len(keyword_hits),
        "semantic_hits_count": len(semantic_hits),
        "filtered_file_count": filtered_file_count,
        "search_mode": "hybrid",
        "semantic_intent": semantic_intent or {},

        "filename": filename,
        "doc_role": doc_role,
        "section_title": section_title,
        "section_date": section_date,
        "section_type": section_type,
        "financial_topic": financial_topic,
    }


def _merge_multi_query_hits(
    query_results: List[Dict[str, Any]],
    limit: int,
    semantic_intent: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}

    for result in query_results:
        query = result.get("query", "")
        hits = result.get("hits", []) or []

        for hit in hits:
            key = _dedupe_key(hit)

            if key not in merged:
                row = dict(hit)
                row["matched_queries"] = [query] if query else []
                row["multi_query_hit_count"] = 1
                merged[key] = row
                continue

            existing = merged[key]

            matched_queries = existing.get("matched_queries", []) or []
            if query and query not in matched_queries:
                matched_queries.append(query)
            existing["matched_queries"] = matched_queries
            existing["multi_query_hit_count"] = len(matched_queries)

            existing_intent = int(existing.get("intent_match_score", 0))
            new_intent = int(hit.get("intent_match_score", 0))

            existing_rrf = float(existing.get("rrf_score", 0.0))
            new_rrf = float(hit.get("rrf_score", 0.0))

            existing_score = float(existing.get("score", 0.0))
            new_score = float(hit.get("score", 0.0))

            if (
                new_intent > existing_intent
                or (new_intent == existing_intent and new_rrf > existing_rrf)
                or (new_intent == existing_intent and new_rrf == existing_rrf and new_score > existing_score)
            ):
                row = dict(hit)
                row["matched_queries"] = matched_queries
                row["multi_query_hit_count"] = len(matched_queries)
                merged[key] = row

    out = list(merged.values())

    out = _apply_semantic_intent_boost(out, semantic_intent=semantic_intent)

    return out[:limit]


async def hybrid_retrieve_multi_query(
    ctx,
    *,
    queries: List[str],
    limit: int = 10,
    domains: list[str] | None = None,
    file_type: str | None = None,
    source: str | None = None,
    per_query_limit: int | None = None,
    filename: str | None = None,
    doc_role: str | None = None,
    section_title: str | None = None,
    section_date: str | None = None,
    section_type: str | None = None,
    financial_topic: str | None = None,

    # ✅ 新增这两行
    file_id: str | None = None,
    semantic_intent: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    clean_queries = []
    seen = set()

    for q in queries or []:
        s = (q or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        clean_queries.append(s)

    if not clean_queries:
        return {
            "ok": False,
            "reason": "empty queries",
            "hits": [],
        }

    limit = max(1, min(int(limit), 50))

    if per_query_limit is None:
        per_query_limit = max(limit * 2, 10)

    per_query_limit = max(1, min(int(per_query_limit), 50))

    query_results: List[Dict[str, Any]] = []

    for q in clean_queries:
        out = await hybrid_retrieve(
            ctx,
            query=q,
            limit=per_query_limit,
            domains=domains,
            file_type=file_type,
            source=source,
            filename=filename,
            doc_role=doc_role,
            section_title=section_title,
            section_date=section_date,
            file_id=file_id,
            semantic_intent=semantic_intent,
            section_type=section_type,
            financial_topic=financial_topic,
        )
        if out.get("ok"):
            query_results.append(out)

    if not query_results:
        return {
            "ok": False,
            "reason": "all multi-query retrieval failed",
            "hits": [],
        }

    merged_hits = _merge_multi_query_hits(
        query_results=query_results,
        limit=limit,
        semantic_intent=semantic_intent,
    )

    return {
        "ok": True,
        "queries": clean_queries,
        "domains": domains,
        "file_type": file_type,
        "source": source,
        "file_id": file_id,
        "hits": merged_hits,
        "hits_total": len(merged_hits),
        "query_results_count": len(query_results),
        "search_mode": "hybrid_multi_query",
        "semantic_intent": semantic_intent or {},

        "filename": filename,
        "doc_role": doc_role,
        "section_title": section_title,
        "section_date": section_date,
        "section_type": section_type,
        "financial_topic": financial_topic,
    }