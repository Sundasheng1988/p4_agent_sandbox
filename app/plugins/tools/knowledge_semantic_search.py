# knowledge_semantic_search
from __future__ import annotations

import json
import re
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


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())


def _extract_terms(query: str) -> List[str]:
    q = (query or "").strip()

    weak_words = ["如何", "怎么", "怎样", "请问", "一下"]
    for w in weak_words:
        q = q.replace(w, " ")

    q = re.sub(r"[，。！？、,.!?\-_/]+", " ", q)
    q = re.sub(r"\s+", " ", q).strip()

    terms: List[str] = []
    if q:
        terms.append(q)

    for part in q.split():
        if len(part.strip()) >= 2 and part.strip() not in terms:
            terms.append(part.strip())

    candidates = [
        "重建知识库",
        "清空知识库",
        "知识库运行数据",
        "运行数据",
        "知识索引",
        "文本块",
        "知识向量",
        "语义搜索",
        "知识问答",
        "启动服务",
        "构建知识索引",
        "构建文本块",
        "构建知识向量",
    ]
    for c in candidates:
        if c in q and c not in terms:
            terms.append(c)

    return terms


def _compute_rerank_bonus(
    *,
    query: str,
    filename: str,
    section_title: str,
    heading_level: int,
    snippet: str,
) -> float:
    bonus = 0.0

    q_norm = _normalize_text(query)
    title_norm = _normalize_text(section_title)
    snippet_norm = _normalize_text(snippet)

    terms = _extract_terms(query)

    if q_norm and title_norm:
        if q_norm == title_norm:
            bonus += 0.16
        elif q_norm in title_norm:
            bonus += 0.12
        elif title_norm in q_norm and len(title_norm) >= 4:
            bonus += 0.08

    title_hits = 0
    for t in terms:
        t_norm = _normalize_text(t)
        if t_norm and title_norm and t_norm in title_norm:
            title_hits += 1
    bonus += min(title_hits * 0.03, 0.12)

    snippet_hits = 0
    for t in terms:
        t_norm = _normalize_text(t)
        if t_norm and snippet_norm and t_norm in snippet_norm:
            snippet_hits += 1
    bonus += min(snippet_hits * 0.01, 0.04)

    if (filename or "").lower() in {"ops_playbook.md", "playbook.md", "faq.md", "runbook.md"}:
        bonus += 0.01

    if heading_level == 1:
        if title_norm and snippet_norm and title_norm == snippet_norm and len(snippet_norm) <= 40:
            bonus -= 0.15

    generic_titles = {
        "chunk",
        "runtime",
        "audit",
        "taskstore",
        "rag",
        "ragpipeline",
        "orchestrator",
        "safetoolexecutor",
    }
    if title_norm in generic_titles:
        bonus -= 0.03

    bonus = min(bonus, 0.28)
    return bonus


def _load_file_meta(sandbox_root: Path, file_id: str) -> Dict[str, Any]:
    meta_path = sandbox_root / "uploads" / file_id / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return _load_json(meta_path)
    except Exception:
        return {}


def _match_filters(
    *,
    file_meta: Dict[str, Any],
    domain: str | None,
    file_type: str | None,
    source: str | None,
) -> bool:
    if domain and file_meta.get("domain") != domain:
        return False
    if file_type and file_meta.get("file_type") != file_type:
        return False
    if source and file_meta.get("source") != source:
        return False
    return True


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}

    query = str(args.get("query", "")).strip()
    limit = int(args.get("limit", 10))
    domain = args.get("domain")
    file_type = args.get("file_type")
    source = args.get("source")

    if domain is not None:
        domain = str(domain).strip() or None
    if file_type is not None:
        file_type = str(file_type).strip() or None
    if source is not None:
        source = str(source).strip() or None

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
            "domain": domain,
            "file_type": file_type,
            "source": source,
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
            "domain": domain,
            "file_type": file_type,
            "source": source,
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
    filtered_file_count = 0

    for item in items:
        file_id = item.get("file_id", "")
        filename = item.get("filename", "")
        manifest_rel = item.get("record_path")

        if not manifest_rel:
            continue

        file_meta = {
            "domain": item.get("domain"),
            "file_type": item.get("file_type"),
            "source": item.get("source"),
        }

        if not any(file_meta.values()):
            full_meta = _load_file_meta(sandbox_root=sandbox_root, file_id=file_id)
            file_meta = {
                "domain": full_meta.get("domain"),
                "file_type": full_meta.get("file_type"),
                "source": full_meta.get("source"),
            }

        if not _match_filters(
            file_meta=file_meta,
            domain=domain,
            file_type=file_type,
            source=source,
        ):
            continue

        filtered_file_count += 1

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
                base_score = cosine_score(query_vec, doc_vec)
            except Exception:
                continue

            snippet = _snippet_from_preview(row.get("text_preview", ""))
            section_title = row.get("section_title", "") or ""
            heading_level = int(row.get("heading_level", 0) or 0)
            section_path = row.get("section_path", []) or []

            rerank_bonus = _compute_rerank_bonus(
                query=query,
                filename=filename,
                section_title=section_title,
                heading_level=heading_level,
                snippet=snippet,
            )
            rerank_score = float(base_score) + float(rerank_bonus)

            hit = {
                "file_id": file_id,
                "filename": filename,
                "chunk_id": row.get("chunk_id"),
                "chunk_index": row.get("chunk_index"),
                "score": round(float(base_score), 6),
                "rerank_score": round(float(rerank_score), 6),
                "rerank_bonus": round(float(rerank_bonus), 6),
                "snippet": snippet,
                "section_title": section_title,
                "heading_level": heading_level,
                "section_path": section_path,
                "start": row.get("start"),
                "end": row.get("end"),
                "search_mode": "semantic",
                "domain": file_meta.get("domain"),
                "file_type": file_meta.get("file_type"),
                "source": file_meta.get("source"),
            }
            hits.append((rerank_score, hit))

    hits.sort(key=lambda x: x[0], reverse=True)
    top_hits = [h for _, h in hits[:limit]]

    return {
        "ok": True,
        "query": query,
        "limit": limit,
        "domain": domain,
        "file_type": file_type,
        "source": source,
        "model_name": model_name,
        "hits": top_hits,
        "hits_total": len(hits),
        "filtered_file_count": filtered_file_count,
    }


TOOL = ToolSpec(
    name="knowledge_semantic_search",
    handler=_handler,
    risk="low",
    description="Semantic search over chunk embeddings using cosine similarity + lightweight rerank.",
    args_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "domain": {"type": ["string", "null"]},
            "file_type": {"type": ["string", "null"]},
            "source": {"type": ["string", "null"]},
        },
        "required": ["query"],
    },
)