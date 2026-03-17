# files_list
from __future__ import annotations
from typing import Any, Dict, List

from app.tools.spec import ToolSpec

async def _handler(ctx, args: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = int(args.get("limit", 10))
    return await ctx.store.list_files(limit=limit)

TOOL = ToolSpec(
    name="files_list",
    handler=_handler,
    risk="low",
    description="List uploaded files from SQLite.",
    args_schema={
        "type": "object",
        "properties": {"limit": {"type": "integer"}},
        "required": [],
    },
)