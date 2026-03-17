from __future__ import annotations

from typing import Any, Dict
from app.tools.spec import ToolSpec


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    file_id = str(args.get("file_id", "")).strip()
    if not file_id:
        raise ValueError("missing required arg: file_id")

    rec = await ctx.store.get_file(file_id)
    if not rec:
        raise ValueError("file not found")
    return rec


TOOL = ToolSpec(
    name="file_meta",
    handler=_handler,
    risk="low",
    description="Get file metadata by file_id from SQLite.",
    args_schema={
        "type": "object",
        "properties": {"file_id": {"type": "string"}},
        "required": ["file_id"],
    },
)