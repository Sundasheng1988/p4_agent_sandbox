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
            # semantic 通常保留更丰富字段
            for field in [
                "rerank_score", "rerank_bonus", "section_title",
                "heading_level", "section_path", "start", "end"
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
    domain: str | None = None,
    file_type: str | None = None,
    source: str | None = None,
) -> Dict[str, Any]:
    keyword_out = await keyword_search_handler(ctx, {
        "query": query,
        "limit": max(limit * 2, 10),
        "mode": "text",
        "domain": domain,
        "file_type": file_type,
        "source": source,
    })

    semantic_out = await semantic_search_handler(ctx, {
        "query": query,
        "limit": max(limit * 2, 10),
        "domain": domain,
        "file_type": file_type,
        "source": source,
    })

    keyword_hits = keyword_out.get("hits", []) if isinstance(keyword_out, dict) else []
    semantic_hits = semantic_out.get("hits", []) if isinstance(semantic_out, dict) else []

    all_fused = rrf_fuse(keyword_hits, semantic_hits)

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
        "domain": domain,
        "file_type": file_type,
        "source": source,
        "hits": fused,
        "hits_total": len(all_fused),
        "keyword_hits_count": len(keyword_hits),
        "semantic_hits_count": len(semantic_hits),
        "filtered_file_count": filtered_file_count,
        "search_mode": "hybrid",
    }