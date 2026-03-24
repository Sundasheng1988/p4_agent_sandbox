#knowledge_build_chunks.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from app.core.chunking import build_chunks_for_text
from app.tools.spec import ToolSpec


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}

    limit = int(args.get("limit", 500))
    max_chars = int(args.get("max_chars", 50000))
    chunk_size = int(args.get("chunk_size", 800))
    overlap = int(args.get("overlap", 120))
    force = bool(args.get("force", False))

    if chunk_size < 100 or chunk_size > 5000:
        raise ValueError("chunk_size must be 100..5000")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >=0 and < chunk_size")
    if max_chars < 1000 or max_chars > 500000:
        raise ValueError("max_chars must be 1000..500000")

    sandbox_root = Path(ctx.sandbox_root)
    artifacts_dir = sandbox_root / "artifacts"
    chunks_dir = artifacts_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    files = await ctx.store.list_files(limit=limit)

    index_items: List[Dict[str, Any]] = []
    created = 0
    rebuilt = 0
    skipped = 0
    total_chunks = 0

    for meta in files:
        file_id = meta["file_id"]
        filename = meta.get("filename", "")
        sha256 = meta.get("sha256")

        out_path = chunks_dir / f"{file_id}.chunks.json"

        # 增量跳过
        if (not force) and out_path.exists():
            try:
                old = _load_json(out_path)
                same_sha = old.get("sha256") == sha256
                same_chunk_size = int(old.get("chunk_size", -1)) == chunk_size
                same_overlap = int(old.get("overlap", -1)) == overlap
                same_max_chars = int(old.get("max_chars", -1)) == max_chars

                if same_sha and same_chunk_size and same_overlap and same_max_chars:
                    skipped += 1
                    total_chunks += len(old.get("chunks", []))
                    index_items.append(
                        {
                            "file_id": file_id,
                            "filename": filename,
                            "sha256": sha256,
                            "chunk_count": len(old.get("chunks", [])),
                            "record_path": str(out_path.relative_to(sandbox_root)),
                            "updated_at": old.get("updated_at"),
                        }
                    )
                    continue
                else:
                    rebuilt += 1
            except Exception:
                rebuilt += 1
        else:
            created += 1

        parsed = await ctx.file_service.parse_text_by_id(
            file_id=file_id,
            max_chars=max_chars,
        )
        text = parsed.get("text", "") or ""

        chunks = build_chunks_for_text(
            file_id=file_id,
            filename=filename,
            text=text,
            chunk_size=chunk_size,
            overlap=overlap,
        )

        record = {
            "file_id": file_id,
            "filename": filename,
            "sha256": sha256,
            "max_chars": max_chars,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "source_chars": len(text),
            "chunk_count": len(chunks),
            "updated_at": time.time(),
            "chunks": chunks,
        }

        _write_json(out_path, record)

        total_chunks += len(chunks)
        index_items.append(
            {
                "file_id": file_id,
                "filename": filename,
                "sha256": sha256,
                "chunk_count": len(chunks),
                "record_path": str(out_path.relative_to(sandbox_root)),
                "updated_at": record["updated_at"],
            }
        )

    index = {
        "version": "m2.5.1-v2",
        "updated_at": time.time(),
        "chunk_size": chunk_size,
        "overlap": overlap,
        "max_chars": max_chars,
        "stats": {
            "files_total": len(files),
            "created": created,
            "rebuilt": rebuilt,
            "skipped": skipped,
            "total_chunks": total_chunks,
        },
        "items": index_items,
    }

    _write_json(artifacts_dir / "chunk_index.json", index)

    return {
        "ok": True,
        "files_total": len(files),
        "created": created,
        "rebuilt": rebuilt,
        "skipped": skipped,
        "total_chunks": total_chunks,
        "chunk_size": chunk_size,
        "overlap": overlap,
    }


TOOL = ToolSpec(
    name="knowledge_build_chunks",
    handler=_handler,
    risk="low",
    description="Build text chunks from parsed file text for later embedding/vector search.",
    args_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
            "max_chars": {"type": "integer", "minimum": 1000, "maximum": 500000},
            "chunk_size": {"type": "integer", "minimum": 100, "maximum": 5000},
            "overlap": {"type": "integer", "minimum": 0, "maximum": 4999},
            "force": {"type": "boolean"},
        },
    },
)