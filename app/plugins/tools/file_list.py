# app/plugins/tools/file_list.py
from __future__ import annotations
from typing import Any, Dict, List
from pathlib import Path
import os

from app.tools.spec import ToolSpec


def _resolve_under_sandbox(sandbox_root: Path, user_path: str) -> Path:
    if not user_path:
        raise ValueError("path is required")

    p0 = Path(os.path.expanduser(user_path))
    p = p0 if p0.is_absolute() else (sandbox_root / p0)
    p = p.resolve()

    # 更稳的校验：要求 resolved path 必须在 sandbox_root 内
    # Python 3.10 支持 is_relative_to
    if not p.is_relative_to(sandbox_root):
        raise ValueError(
            f"path must be under sandbox: {sandbox_root}; "
            f"user_path={user_path!r}; expanded={str(p0)!r}; resolved={str(p)!r}"
        )
    return p


async def _handler(ctx, args: Dict[str, Any]) -> List[Dict[str, Any]]:
    # raise ValueError(f"FILE_LIST_V2_LOADED file={__file__} sandbox_root={getattr(ctx,'sandbox_root',None)!r} args={(args or {})!r}")
    args = args or {}
    path = str(args.get("path", "")).strip()
    limit = int(args.get("limit", 200))

    sandbox_root = Path(ctx.sandbox_root).resolve()
    target = _resolve_under_sandbox(sandbox_root, path)

    if not target.exists():
        raise FileNotFoundError(str(target))
    if not target.is_dir():
        raise ValueError("path is not a directory")

    items: List[Dict[str, Any]] = []
    for i, child in enumerate(sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))):
        if i >= limit:
            break
        st = child.stat()
        items.append(
            {
                "name": child.name,
                "is_dir": child.is_dir(),
                "size": int(st.st_size),
                "mtime": float(st.st_mtime),
            }
        )
    return items


TOOL = ToolSpec(
    name="file_list",
    handler=_handler,
    risk="low",
    description="List directory entries under sandbox_root by path (filesystem, not SQLite).",
    args_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 2000},
        },
        "required": ["path"],
    },
)