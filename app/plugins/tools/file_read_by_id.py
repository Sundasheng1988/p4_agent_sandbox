from __future__ import annotations
import os
from typing import Any, Dict

from app.tools.spec import ToolSpec


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    file_id = str(args["file_id"])
    max_bytes = int(args.get("max_bytes", 200000))

    rec = await ctx.store.get_file(file_id)
    if not rec:
        raise ValueError("file not found")

    raw_path = os.path.join(ctx.sandbox_root, rec["rel_dir"], rec["raw_name"])

    # 二次保险：必须在 sandbox 下
    raw_path = os.path.abspath(os.path.expanduser(raw_path))
    sandbox_root = os.path.abspath(os.path.expanduser(ctx.sandbox_root))
    if not raw_path.startswith(sandbox_root):
        raise ValueError("path out of sandbox")

    with open(raw_path, "rb") as f:
        data = f.read(max_bytes)

    # 先只支持文本（C1-2 目标）
    text = data.decode("utf-8", errors="replace")
    return {"file_id": file_id, "text": text}


TOOL = ToolSpec(
    name="file_read_by_id",
    handler=_handler,
    risk="low",
    description="Read raw file content by file_id (text-first).",
    args_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "max_bytes": {"type": "integer"},
        },
        "required": ["file_id"],
    },
)