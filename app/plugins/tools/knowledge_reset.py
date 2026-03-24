# knowledge_reset.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from app.tools.spec import ToolSpec


def _safe_unlink(path: Path) -> bool:
    try:
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except Exception:
        return False
    return False


def _safe_delete_children(dir_path: Path) -> Dict[str, Any]:
    """
    仅删除目录下的直接子文件/子目录内容，不删除目录本身。
    """
    deleted_files = 0
    deleted_dirs = 0
    failed: List[str] = []

    if not dir_path.exists():
        return {
            "exists": False,
            "deleted_files": 0,
            "deleted_dirs": 0,
            "failed": [],
        }

    for child in dir_path.iterdir():
        try:
            if child.is_file():
                child.unlink()
                deleted_files += 1
            elif child.is_dir():
                # 递归删除整个子目录
                for sub in sorted(child.rglob("*"), reverse=True):
                    if sub.is_file():
                        sub.unlink()
                    elif sub.is_dir():
                        sub.rmdir()
                child.rmdir()
                deleted_dirs += 1
        except Exception:
            failed.append(str(child))

    return {
        "exists": True,
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "failed": failed,
    }


def _ensure_under_sandbox(root: Path, target: Path) -> None:
    root = root.resolve()
    target = target.resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(f"path escapes sandbox: {target}")


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}

    reset_db = bool(args.get("reset_db", True))
    reset_artifacts = bool(args.get("reset_artifacts", True))
    reset_logs = bool(args.get("reset_logs", False))
    reset_uploads = bool(args.get("reset_uploads", False))
    reset_knowledge_index = bool(args.get("reset_knowledge_index", True))
    reset_chunk_index = bool(args.get("reset_chunk_index", True))
    reset_vector_index = bool(args.get("reset_vector_index", True))

    sandbox_root = Path(ctx.sandbox_root).resolve()

    db_path = sandbox_root / "db" / "app.db"
    artifacts_dir = sandbox_root / "artifacts"
    logs_dir = sandbox_root / "logs"
    uploads_dir = sandbox_root / "uploads"

    _ensure_under_sandbox(sandbox_root, db_path)
    _ensure_under_sandbox(sandbox_root, artifacts_dir)
    _ensure_under_sandbox(sandbox_root, logs_dir)
    _ensure_under_sandbox(sandbox_root, uploads_dir)

    result: Dict[str, Any] = {
        "ok": True,
        "sandbox_root": str(sandbox_root),
        "reset_db": False,
        "reset_artifacts": False,
        "reset_logs": False,
        "reset_uploads": False,
        "details": {},
    }

    # 1) DB
    if reset_db:
        deleted = _safe_unlink(db_path)
        result["reset_db"] = deleted
        result["details"]["db"] = {
            "path": str(db_path.relative_to(sandbox_root)),
            "deleted": deleted,
        }

    # 2) artifacts
    if reset_artifacts:
        deleted_files = 0
        failed: List[str] = []

        # 仅删除知识库运行产物，不删除源码目录
        artifact_targets = [
            artifacts_dir / "knowledge_index.json" if reset_knowledge_index else None,
            artifacts_dir / "chunk_index.json" if reset_chunk_index else None,
            artifacts_dir / "vector_index.json" if reset_vector_index else None,
        ]
        artifact_targets = [p for p in artifact_targets if p is not None]

        for p in artifact_targets:
            try:
                if p.exists() and p.is_file():
                    p.unlink()
                    deleted_files += 1
            except Exception:
                failed.append(str(p))

        subdirs = [
            artifacts_dir / "knowledge",
            artifacts_dir / "chunks",
            artifacts_dir / "vector_manifests",
            artifacts_dir / "vectors",
        ]

        subdir_results = {}
        for subdir in subdirs:
            subdir_results[str(subdir.relative_to(sandbox_root))] = _safe_delete_children(subdir)

        result["reset_artifacts"] = True
        result["details"]["artifacts"] = {
            "deleted_index_files": deleted_files,
            "failed": failed,
            "subdirs": subdir_results,
        }

    # 3) logs
    if reset_logs:
        log_res = _safe_delete_children(logs_dir)
        result["reset_logs"] = True
        result["details"]["logs"] = log_res

    # 4) uploads
    if reset_uploads:
        upload_res = _safe_delete_children(uploads_dir)
        result["reset_uploads"] = True
        result["details"]["uploads"] = upload_res

    # 5) 重新初始化数据库（如果删了 db）
    if reset_db:
        await ctx.store.init()
        result["details"]["db"]["reinitialized"] = True

    return result


TOOL = ToolSpec(
    name="knowledge_reset",
    handler=_handler,
    risk="medium",
    description="Reset knowledge runtime artifacts, database, logs, and optionally uploads.",
    args_schema={
        "type": "object",
        "properties": {
            "reset_db": {"type": "boolean"},
            "reset_artifacts": {"type": "boolean"},
            "reset_logs": {"type": "boolean"},
            "reset_uploads": {"type": "boolean"},
            "reset_knowledge_index": {"type": "boolean"},
            "reset_chunk_index": {"type": "boolean"},
            "reset_vector_index": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
)