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
    简单规则得分：
    - 出现次数越多得分越高
    - 单词边界匹配额外加分（英文）
    """
    if not text or not q:
        return 0
    t = text.lower()
    ql = q.lower().strip()
    if not ql:
        return 0

    # 基础：出现次数
    count = t.count(ql)

    # 英文单词边界加权（对 alice/rabbit 这类更友好）
    word_bonus = 0
    if re.fullmatch(r"[a-z0-9_]+", ql):
        word_bonus = len(re.findall(rf"\b{re.escape(ql)}\b", t))

    return count * 3 + word_bonus * 5


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}
    query = _normalize(str(args.get("query", "")))
    limit = int(args.get("limit", 10))
    mode = _normalize(str(args.get("mode", "summary"))).lower()  # summary | text

    if not query:
        raise ValueError("query is required")
    if limit < 1 or limit > 50:
        raise ValueError("limit must be 1..50")
    if mode not in ("summary", "text"):
        raise ValueError("mode must be 'summary' or 'text'")

    sandbox_root = Path(ctx.sandbox_root)
    artifacts_dir = sandbox_root / "artifacts"
    knowledge_dir = artifacts_dir / "knowledge"

    if not knowledge_dir.exists():
        return {"ok": True, "query": query, "hits": [], "reason": "knowledge_dir not found"}

    hits: List[Tuple[int, Dict[str, Any]]] = []

    # 扫描所有 summary.json
    for p in sorted(knowledge_dir.glob("*.summary.json")):
        try:
            rec = _safe_load_json(p)
        except Exception:
            continue

        file_id = rec.get("file_id") or p.stem.replace(".summary", "")
        filename = rec.get("filename") or ""
        summary = rec.get("summary") or ""
        source_chars = int(rec.get("source_chars") or 0)

        # 选择搜索域
        if mode == "summary":
            corpus = summary
        elif mode == "text":
            try:
                parsed = await ctx.file_service.parse_text_by_id(file_id=file_id)
                corpus = parsed.get("text", "")
            except Exception:
                corpus = ""

        else:
            corpus = summary

        score = _score_text(corpus, query)
        corpus_chars = len(corpus)
        if score <= 0:
            continue

        hits.append(
            (
                score,
                {
                    "file_id": file_id,
                    "filename": filename,
                    "score": score,
                    "snippet": _snippet(corpus, query),
                    "source_chars": source_chars,
                    # 新增字段
                    "corpus_chars": corpus_chars,
                    "search_mode": mode,
                    "record_path": str(p.relative_to(sandbox_root)),
                },
            )
        )

    hits.sort(key=lambda x: x[0], reverse=True)
    top = [h for _, h in hits[:limit]]

    return {
        "ok": True,
        "query": query,
        "mode": mode,
        "limit": limit,
        "hits": top,
        "hits_total": len(hits),
    }


TOOL = ToolSpec(
    name="knowledge_search",
    handler=_handler,
    risk="low",
    description="Search in knowledge corpus by summary or parsed text (baseline keyword/full-text search).",
    args_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "mode": {"type": "string", "enum": ["summary", "text"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["query"],
    },
)