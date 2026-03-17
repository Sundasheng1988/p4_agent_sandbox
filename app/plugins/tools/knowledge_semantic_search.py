from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from app.core.embeddings import embed_query, cosine_score
from app.tools.spec import ToolSpec


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _snippet_from_preview(text_preview: str, max_len: int = 160) -> str:
    s = (text_preview or "").strip()
    if len(s) <= max_len:
        return s
    return s[:max_len].rstrip() + "..."


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}

    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 10))

    if not query:
        raise ValueError("query is required")
    if limit < 1 or limit > 50:
        raise ValueError("limit must be 1..50")

    sandbox_root = Path(ctx.sandbox_root)
    artifacts_dir = sandbox_root / "artifacts"
    vector_index_path = artifacts_dir / "vector_index.json"

    if not vector_index_path.exists():
        return {
            "ok": True,
            "query": query,
            "limit": limit,
            "hits": [],
            "hits_total": 0,
            "reason": "vector_index.json not found; run knowledge_build_embeddings first",
        }

    vector_index = _load_json(vector_index_path)
    model_name = str(vector_index.get("model_name", "all-MiniLM-L6-v2")).strip()
    normalize = bool(vector_index.get("normalize", True))
    items = vector_index.get("items", [])

    if not items:
        return {
            "ok": True,
            "query": query,
            "limit": limit,
            "hits": [],
            "hits_total": 0,
            "reason": "vector index is empty",
        }

    query_vec = embed_query(
        query=query,
        model_name=model_name,
        normalize=normalize,
    )

    hits: List[Tuple[float, Dict[str, Any]]] = []

    for item in items:
        file_id = item.get("file_id", "")
        filename = item.get("filename", "")
        manifest_rel = item.get("record_path")

        if not manifest_rel:
            continue

        manifest_path = sandbox_root / manifest_rel
        if not manifest_path.exists():
            continue

        try:
            manifest = _load_json(manifest_path)
        except Exception:
            continue

        for row in manifest.get("vectors", []):
            vector_rel = row.get("vector_path")
            if not vector_rel:
                continue

            vector_path = sandbox_root / vector_rel
            if not vector_path.exists():
                continue

            try:
                doc_vec = np.load(vector_path).astype(np.float32)
            except Exception:
                continue

            try:
                score = cosine_score(query_vec, doc_vec)
            except Exception:
                continue

            hit = {
                "file_id": file_id,
                "filename": filename,
                "chunk_id": row.get("chunk_id"),
                "chunk_index": row.get("chunk_index"),
                "score": round(float(score), 6),
                "snippet": _snippet_from_preview(row.get("text_preview", "")),
                "start": row.get("start"),
                "end": row.get("end"),
                "search_mode": "semantic",
            }
            hits.append((score, hit))

    hits.sort(key=lambda x: x[0], reverse=True)
    top_hits = [h for _, h in hits[:limit]]

    return {
        "ok": True,
        "query": query,
        "limit": limit,
        "model_name": model_name,
        "hits": top_hits,
        "hits_total": len(hits),
    }


TOOL = ToolSpec(
    name="knowledge_semantic_search",
    handler=_handler,
    risk="low",
    description="Semantic search over chunk embeddings using cosine similarity.",
    args_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
    },
)