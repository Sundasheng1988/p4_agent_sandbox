from __future__ import annotations
import os

SANDBOX_ROOT = os.path.expanduser("~/p4_agent_sandbox")


def _abs(p: str) -> str:
    p = os.path.expanduser(p)
    if not p.startswith(SANDBOX_ROOT):
        raise PermissionError(f"path must be under {SANDBOX_ROOT}")
    return p


def file_list(args):
    path = _abs(args.get("path", SANDBOX_ROOT))
    return sorted(os.listdir(path))


def file_read(args):
    path = _abs(args["path"])
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def file_write(args):
    path = _abs(args["path"])
    content = str(args.get("content", ""))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return {"written": len(content), "path": path}
