# app/plugins/tools/knowledge_search.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.tools.spec import ToolSpec


def _safe_load_json(p: Path) -> Dict[str, Any]:
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize(s: str) -> str:
    return (s or "").strip()


def _snippet(text: str, q: str, window: int = 80) -> str:
    """
    返回命中位置附近的一段片段，便于人眼查看。
    """
    if not text or not q:
        return ""
    t = text
    qn = q.strip()
    idx = t.lower().find(qn.lower())
    if idx < 0:
        return t[: min(len(t), window * 2)].strip()
    start = max(0, idx - window)
    end = min(len(t), idx + len(qn) + window)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(t) else ""
    return (prefix + t[start:end].strip() + suffix).strip()


def _score_text(text: str, q: str) -> int:
    """
    chunk 级 keyword/full-text 打分：
    - query 整串出现次数
    - 英文 token / 数字 token / 下划线 token 命中
    - 英文单词边界额外加分
    - 中文短语命中
    """
    if not text or not q:
        return 0

    t = text.lower()
    ql = q.lower().strip()
    if not ql:
        return 0

    score = 0

    # 1) query 整串命中
    whole_count = t.count(ql)
    score += whole_count * 8

    # 2) 英文 token / 数字 token / 下划线 token
    en_tokens = re.findall(r"[a-z0-9_\-]{2,}", ql)
    for tok in en_tokens:
        count = t.count(tok)
        score += count * 3
        if re.fullmatch(r"[a-z0-9_]+", tok):
            word_bonus = len(re.findall(rf"\b{re.escape(tok)}\b", t))
            score += word_bonus * 5

    # 3) 中文短语切分（极简）
    zh_parts = re.findall(r"[\u4e00-\u9fff]{2,}", q)
    for part in zh_parts:
        part = part.strip().lower()
        if not part:
            continue
        count = t.count(part)
        score += count * 4

    return score


def _load_file_meta(sandbox_root: Path, file_id: str) -> Dict[str, Any]:
    meta_path = sandbox_root / "uploads" / file_id / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return _safe_load_json(meta_path)
    except Exception:
        return {}


def _meta_match(
    meta: Dict[str, Any],
    domains: List[str] | None,
    file_type: str | None,
    source: str | None,
) -> bool:
    if domains is not None and str(meta.get("domain")) not in domains:
        return False
    if file_type is not None and str(meta.get("file_type")) != str(file_type):
        return False
    if source is not None and str(meta.get("source")) != str(source):
        return False
    return True


def _build_summary_hits(
    *,
    sandbox_root: Path,
    knowledge_dir: Path,
    query: str,
    limit: int,
    domains: List[str] | None,
    file_type: str | None,
    source: str | None,
) -> Dict[str, Any]:
    """
    summary 模式：保留文件级搜索
    """
    hits: List[Tuple[int, Dict[str, Any]]] = []
    filtered_file_ids = set()

    for p in sorted(knowledge_dir.glob("*.summary.json")):
        try:
            rec = _safe_load_json(p)
        except Exception:
            continue

        file_id = rec.get("file_id") or p.stem.replace(".summary", "")
        filename = rec.get("filename") or ""
        summary = rec.get("summary") or ""
        source_chars = int(rec.get("source_chars") or 0)

        meta = _load_file_meta(sandbox_root, file_id=file_id)
        if not _meta_match(meta, domains=domains, file_type=file_type, source=source):
            continue

        filtered_file_ids.add(file_id)

        score = _score_text(summary, query)
        if score <= 0:
            continue

        hit = {
            "file_id": file_id,
            "filename": filename,
            "chunk_id": None,
            "chunk_index": None,
            "score": score,
            "snippet": _snippet(summary, query),
            "source_chars": source_chars,
            "corpus_chars": len(summary),
            "search_mode": "summary",
            "record_path": str(p.relative_to(sandbox_root)),
            "section_title": "",
            "heading_level": 0,
            "section_path": [],
            "start": None,
            "end": None,
            "domain": meta.get("domain"),
            "file_type": meta.get("file_type"),
            "source": meta.get("source"),
        }
        hits.append((score, hit))

    hits.sort(key=lambda x: x[0], reverse=True)
    top = [h for _, h in hits[:limit]]

    return {
        "hits": top,
        "hits_total": len(hits),
        "filtered_file_count": len(filtered_file_ids),
    }


def _build_text_hits(
    *,
    sandbox_root: Path,
    chunks_dir: Path,
    query: str,
    limit: int,
    domains: List[str] | None,
    file_type: str | None,
    source: str | None,
) -> Dict[str, Any]:
    """
    text 模式：chunk 级搜索
    """
    hits: List[Tuple[int, Dict[str, Any]]] = []
    filtered_file_ids = set()

    for p in sorted(chunks_dir.glob("*.chunks.json")):
        try:
            rec = _safe_load_json(p)
        except Exception:
            continue

        file_id = rec.get("file_id") or p.stem.replace(".chunks", "")
        filename = rec.get("filename") or ""
        chunks = rec.get("chunks", []) or []

        meta = _load_file_meta(sandbox_root, file_id=file_id)
        if not _meta_match(meta, domains=domains, file_type=file_type, source=source):
            continue

        filtered_file_ids.add(file_id)

        for c in chunks:
            text = str(c.get("text", "") or "")
            score = _score_text(text, query)
            if score <= 0:
                continue

            hit = {
                "file_id": file_id,
                "filename": filename,
                "chunk_id": c.get("chunk_id"),
                "chunk_index": c.get("chunk_index"),
                "score": score,
                "snippet": _snippet(text, query),
                "source_chars": len(text),
                "corpus_chars": len(text),
                "search_mode": "text",
                "record_path": str(p.relative_to(sandbox_root)),
                "section_title": c.get("section_title", "") or "",
                "heading_level": int(c.get("heading_level", 0) or 0),
                "section_path": c.get("section_path", []) or [],
                "start": c.get("start"),
                "end": c.get("end"),
                "domain": meta.get("domain"),
                "file_type": meta.get("file_type"),
                "source": meta.get("source"),
            }
            hits.append((score, hit))

    hits.sort(key=lambda x: x[0], reverse=True)
    top = [h for _, h in hits[:limit]]

    return {
        "hits": top,
        "hits_total": len(hits),
        "filtered_file_count": len(filtered_file_ids),
    }


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}

    query = _normalize(str(args.get("query", "")))
    limit = int(args.get("limit", 10))
    mode = _normalize(str(args.get("mode", "summary"))).lower()  # summary | text

    domains = args.get("domains")
    if domains is not None:
        domains = [str(d).strip() for d in domains if str(d).strip()]
        if not domains:
            domains = None

    file_type = args.get("file_type")
    source = args.get("source")

    if file_type is not None:
        file_type = _normalize(str(file_type)) or None
    if source is not None:
        source = _normalize(str(source)) or None

    if not query:
        raise ValueError("query is required")
    if limit < 1 or limit > 50:
        raise ValueError("limit must be 1..50")
    if mode not in ("summary", "text"):
        raise ValueError("mode must be 'summary' or 'text'")

    sandbox_root = Path(ctx.sandbox_root)
    artifacts_dir = sandbox_root / "artifacts"
    knowledge_dir = artifacts_dir / "knowledge"
    chunks_dir = artifacts_dir / "chunks"

    if mode == "summary":
        if not knowledge_dir.exists():
            return {
                "ok": True,
                "query": query,
                "mode": mode,
                "limit": limit,
                "domains": domains,
                "file_type": file_type,
                "source": source,
                "hits": [],
                "reason": "knowledge_dir not found",
            }

        out = _build_summary_hits(
            sandbox_root=sandbox_root,
            knowledge_dir=knowledge_dir,
            query=query,
            limit=limit,
            domains=domains,
            file_type=file_type,
            source=source,
        )

    else:
        if not chunks_dir.exists():
            return {
                "ok": True,
                "query": query,
                "mode": mode,
                "limit": limit,
                "domains": domains,
                "file_type": file_type,
                "source": source,
                "hits": [],
                "reason": "chunks_dir not found",
            }

        out = _build_text_hits(
            sandbox_root=sandbox_root,
            chunks_dir=chunks_dir,
            query=query,
            limit=limit,
            domains=domains,
            file_type=file_type,
            source=source,
        )

    return {
        "ok": True,
        "query": query,
        "mode": mode,
        "limit": limit,
        "domains": domains,
        "file_type": file_type,
        "source": source,
        "hits": out["hits"],
        "hits_total": out["hits_total"],
        "filtered_file_count": out["filtered_file_count"],
    }


TOOL = ToolSpec(
    name="knowledge_search",
    handler=_handler,
    risk="low",
    description="Search in knowledge corpus by summary or chunk-level parsed text.",
    args_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "mode": {"type": "string", "enum": ["summary", "text"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "domains": {
                "type": ["array", "null"],
                "items": {"type": "string"},
            },
            "file_type": {"type": ["string", "null"]},
            "source": {"type": ["string", "null"]},
        },
        "required": ["query"],
    },
)