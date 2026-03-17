#knowledge_build_index.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

from app.tools.spec import ToolSpec


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


async def _handler(ctx, args: Dict[str, Any]):
    args = args or {}

    limit = int(args.get("limit", 500))
    summary_chars = int(args.get("summary_chars", 400))
    force = bool(args.get("force", False))  # True: 强制全量重建，不做增量跳过

    sandbox_root = Path(ctx.sandbox_root)
    artifacts_dir = sandbox_root / "artifacts"
    knowledge_dir = artifacts_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    files = await ctx.store.list_files(limit=limit)

    index_items = []
    created = 0
    rebuilt = 0
    skipped = 0

    for meta in files:
        file_id = meta["file_id"]
        filename = meta.get("filename")
        sha256 = meta.get("sha256")  # ✅ 关键：用它做增量判断

        out_path = knowledge_dir / f"{file_id}.summary.json"

        # =========================
        # M2-2.2 增量跳过
        # =========================
        if (not force) and out_path.exists():
            try:
                old = _load_json(out_path)
                if old.get("sha256") == sha256 and sha256:
                    # 文件内容没变 → 直接复用旧结果
                    index_items.append(old)
                    skipped += 1
                    continue
                else:
                    rebuilt += 1
            except Exception:
                # 旧文件坏了/非 JSON → 当作需要重建
                rebuilt += 1
        else:
            created += 1

        # =========================
        # 需要生成 / 重建
        # =========================
        parsed = await ctx.file_service.parse_text_by_id(file_id=file_id)
        text = parsed.get("text", "") or ""
        summary = text[:summary_chars]

        record = {
            "file_id": file_id,
            "filename": filename,
            "sha256": sha256,
            "summary": summary,
            "summary_chars": summary_chars,
            "source_chars": len(text),
            "created_at": meta.get("created_at"),
            "updated_at": time.time(),
        }

        _write_json(out_path, record)
        index_items.append(record)

    index = {
        "version": "m2-2.2",
        "updated_at": time.time(),
        "items": index_items,
        "stats": {
            "files_total": len(files),
            "created": created,
            "rebuilt": rebuilt,
            "skipped": skipped,
        },
    }

    _write_json(artifacts_dir / "knowledge_index.json", index)

    return {
        "ok": True,
        "files_total": len(files),
        "created": created,
        "rebuilt": rebuilt,
        "skipped": skipped,
    }


TOOL = ToolSpec(
    name="knowledge_build_index",
    handler=_handler,
    description="Build knowledge index from uploaded files (incremental).",
    args_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
            "summary_chars": {"type": "integer", "minimum": 50, "maximum": 2000},
            "force": {"type": "boolean"},
        },
    },
)