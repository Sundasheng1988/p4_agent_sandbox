# hybrid_retrieval
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.plugins.tools.knowledge_search import _handler as keyword_search_handler
from app.plugins.tools.knowledge_semantic_search import _handler as semantic_search_handler


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_full_chunk_text(ctx, file_id: str, chunk_id: str) -> str:
    if not file_id or not chunk_id:
        return ""

    chunk_path = Path(ctx.sandbox_root) / "artifacts" / "chunks" / f"{file_id}.chunks.json"
    if not chunk_path.exists():
        return ""

    try:
        rec = _load_json(chunk_path)
    except Exception:
        return ""

    for c in rec.get("chunks", []) or []:
        if c.get("chunk_id") == chunk_id:
            return (c.get("text") or "").strip()

    return ""


def _dedupe_key(hit: Dict[str, Any]) -> Tuple[str, str]:
    return (
        str(hit.get("file_id", "")),
        str(hit.get("chunk_id", "")),
    )

def _norm_text(v: Any) -> str:
    return str(v or "").strip().lower()


def _match_soft(value: Any, expected: str | None) -> bool:
    if not expected:
        return True

    v = _norm_text(value)
    e = _norm_text(expected)

    if not v:
        return False

    return e in v or v in e


def _hit_matches_constraints(
    hit: Dict[str, Any],
    *,
    filename: str | None = None,
    doc_role: str | None = None,
    section_title: str | None = None,
    section_date: str | None = None,
) -> bool:
    # filename 硬过滤
    if filename:
        if _norm_text(hit.get("filename")) != _norm_text(filename):
            return False

    # doc_role 硬过滤
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

    # section_date 硬过滤
    if section_date:
        hit_section_date = _norm_text(hit.get("section_date"))
        hit_section_title = _norm_text(hit.get("section_title"))

        if hit_section_date:
            if hit_section_date != _norm_text(section_date):
                return False
        else:
            if hit_section_title != _norm_text(section_date):
                return False

    # section_title 软过滤：允许包含关系
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

def rrf_fuse(
    keyword_hits: List[Dict[str, Any]],
    semantic_hits: List[Dict[str, Any]],
    k: int = 60,
) -> List[Dict[str, Any]]:
    """
    Reciprocal Rank Fusion
    score = sum(1 / (k + rank))
    """
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
                "section_title",
                "heading_level",
                "section_path",
                "start",
                "end",
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
) -> Dict[str, Any]:
    keyword_out = await keyword_search_handler(
        ctx,
        {
            "query": query,
            "limit": max(limit * 2, 10),
            "mode": "text",
            "domains": domains,
            "file_type": file_type,
            "source": source,
        },
    )

    semantic_out = await semantic_search_handler(
        ctx,
        {
            "query": query,
            "limit": max(limit * 2, 10),
            "domains": domains,
            "file_type": file_type,
            "source": source,
        },
    )

    keyword_hits = keyword_out.get("hits", []) if isinstance(keyword_out, dict) else []
    semantic_hits = semantic_out.get("hits", []) if isinstance(semantic_out, dict) else []

    all_fused = rrf_fuse(keyword_hits, semantic_hits)
    all_fused = _filter_hits_by_constraints(
        all_fused,
        filename=filename,
        doc_role=doc_role,
        section_title=section_title,
        section_date=section_date,
    )

    for hit in all_fused:
        if not hit.get("full_text"):
            hit["full_text"] = _get_full_chunk_text(
                ctx,
                file_id=str(hit.get("file_id", "")),
                chunk_id=str(hit.get("chunk_id", "")),
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
        "hits": fused,
        "hits_total": len(all_fused),
        "keyword_hits_count": len(keyword_hits),
        "semantic_hits_count": len(semantic_hits),
        "filtered_file_count": filtered_file_count,
        "search_mode": "hybrid",

        "filename": filename,
        "doc_role": doc_role,
        "section_title": section_title,
        "section_date": section_date,
    }

def _merge_multi_query_hits(
    query_results: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    合并多个 query 的 hybrid retrieval 结果
    去重键：file_id + chunk_id
    对重复命中的 chunk：
    - 保留更高的 rrf_score
    - 记录命中了哪些 query
    """
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

            # 记录命中 query
            matched_queries = existing.get("matched_queries", []) or []
            if query and query not in matched_queries:
                matched_queries.append(query)
            existing["matched_queries"] = matched_queries
            existing["multi_query_hit_count"] = len(matched_queries)

            # 保留更强分数
            existing_rrf = float(existing.get("rrf_score", 0.0))
            new_rrf = float(hit.get("rrf_score", 0.0))

            existing_score = float(existing.get("score", 0.0))
            new_score = float(hit.get("score", 0.0))

            if (new_rrf > existing_rrf) or (new_rrf == existing_rrf and new_score > existing_score):
                # 用新 hit 覆盖主要字段，但保留 matched_queries
                row = dict(hit)
                row["matched_queries"] = matched_queries
                row["multi_query_hit_count"] = len(matched_queries)
                merged[key] = row

    out = list(merged.values())

    # multi_query_hit_count 作为额外 boost
    out.sort(
        key=lambda x: (
            int(x.get("multi_query_hit_count", 1)),
            float(x.get("rrf_score", 0.0)),
            float(x.get("rerank_score", x.get("score", 0.0))),
            float(x.get("score", 0.0)),
        ),
        reverse=True,
    )

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
) -> Dict[str, Any]:
    """
    Multi-query retrieval v1
    - 每条 query 单独做 hybrid retrieval
    - 合并结果并去重
    """
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

    if per_query_limit is None:
        per_query_limit = max(limit * 2, 10)

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
    )

    return {
        "ok": True,
        "queries": clean_queries,
        "domains": domains,
        "file_type": file_type,
        "source": source,
        "hits": merged_hits,
        "hits_total": len(merged_hits),
        "query_results_count": len(query_results),
        "search_mode": "hybrid_multi_query",
        "filename": filename,
        "doc_role": doc_role,
        "section_title": section_title,
        "section_date": section_date,
    }