# app/plugins/tools/file_summary_by_id.py
from __future__ import annotations
from typing import Any, Dict

from app.tools.spec import ToolSpec


def _simple_summary(text: str, max_chars: int = 400) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    # 简单规则：先去掉多余空行
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
    t2 = "\n".join(lines)
    if len(t2) <= max_chars:
        return t2
    return t2[:max_chars].rstrip() + "…"


async def _handler(ctx, args: Dict[str, Any]):
    args = args or {}
    file_id = str(args.get("file_id", "")).strip()
    max_chars = int(args.get("max_chars", 20000))
    summary_chars = int(args.get("summary_chars", 400))

    if not file_id:
        raise ValueError("file_id is required")

    parsed = await ctx.file_service.parse_text_by_id(file_id=file_id, max_chars=max_chars)
    text = parsed.get("text") or ""
    summary = _simple_summary(text, summary_chars)

    return {
        "file_id": file_id,
        "summary": summary,
        "summary_chars": summary_chars,
        "source_chars": len(text),
    }


TOOL = ToolSpec(
    name="file_summary_by_id",
    handler=_handler,
    risk="low",
    description="Summarize a file by file_id (uses parsed text first).",
    args_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "max_chars": {"type": "integer", "minimum": 100, "maximum": 200000},
            "summary_chars": {"type": "integer", "minimum": 50, "maximum": 2000},
        },
        "required": ["file_id"],
    },
)