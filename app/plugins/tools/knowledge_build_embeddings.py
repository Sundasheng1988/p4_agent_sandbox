from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

from app.core.embeddings import embed_texts
from app.tools.spec import ToolSpec


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _preview(text: str, max_len: int = 120) -> str:
    s = (text or "").replace("\n", " ").strip()
    if len(s) <= max_len:
        return s
    return s[:max_len].rstrip() + "..."


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}

    limit = int(args.get("limit", 500))
    model_name = str(args.get("model_name", "all-MiniLM-L6-v2")).strip()
    normalize = bool(args.get("normalize", True))
    max_chunks_per_file = int(args.get("max_chunks_per_file", 5000))
    force = bool(args.get("force", False))

    if limit < 1 or limit > 5000:
        raise ValueError("limit must be 1..5000")
    if not model_name:
        raise ValueError("model_name is required")
    if max_chunks_per_file < 1 or max_chunks_per_file > 100000:
        raise ValueError("max_chunks_per_file must be 1..100000")

    sandbox_root = Path(ctx.sandbox_root)
    artifacts_dir = sandbox_root / "artifacts"
    chunks_dir = artifacts_dir / "chunks"
    vectors_dir = artifacts_dir / "vectors"
    manifests_dir = artifacts_dir / "vector_manifests"

    vectors_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    chunk_index_path = artifacts_dir / "chunk_index.json"
    if not chunk_index_path.exists():
        raise FileNotFoundError("artifacts/chunk_index.json not found; run knowledge_build_chunks first")

    chunk_index = _load_json(chunk_index_path)
    chunk_items = chunk_index.get("items", [])[:limit]

    index_items: List[Dict[str, Any]] = []
    created = 0
    rebuilt = 0
    skipped = 0
    total_vectors = 0
    vector_dim = 0

    for item in chunk_items:
        file_id = item["file_id"]
        filename = item.get("filename", "")
        sha256 = item.get("sha256")
        chunk_count_from_index = int(item.get("chunk_count", 0))

        chunk_record_rel = item.get("record_path")
        if not chunk_record_rel:
            continue

        chunk_record_path = sandbox_root / chunk_record_rel
        if not chunk_record_path.exists():
            continue

        manifest_path = manifests_dir / f"{file_id}.vectors.json"

        # 增量跳过
        if (not force) and manifest_path.exists():
            try:
                old = _load_json(manifest_path)
                same_sha = old.get("sha256") == sha256
                same_model_name = old.get("model_name") == model_name
                same_normalize = bool(old.get("normalize", True)) == normalize
                same_chunk_count = int(old.get("chunk_count", -1)) == chunk_count_from_index

                if same_sha and same_model_name and same_normalize and same_chunk_count:
                    skipped += 1
                    old_vectors = old.get("vectors", [])
                    total_vectors += len(old_vectors)
                    if not vector_dim:
                        vector_dim = int(old.get("vector_dim", 0) or 0)

                    index_items.append(
                        {
                            "file_id": file_id,
                            "filename": filename,
                            "sha256": sha256,
                            "chunk_count": chunk_count_from_index,
                            "vector_count": len(old_vectors),
                            "record_path": str(manifest_path.relative_to(sandbox_root)),
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

        chunk_record = _load_json(chunk_record_path)
        chunks = chunk_record.get("chunks", [])[:max_chunks_per_file]

        texts: List[str] = []
        meta_rows: List[Dict[str, Any]] = []

        for ch in chunks:
            text = ch.get("text", "") or ""
            embedding_text = ch.get("embedding_text") or text
            chunk_id = ch.get("chunk_id")
            chunk_index_num = int(ch.get("chunk_index", 0))
            start = int(ch.get("start", 0))
            end = int(ch.get("end", 0))

            section_title = ch.get("section_title", "") or ""
            heading_level = int(ch.get("heading_level", 0) or 0)
            section_path = ch.get("section_path", []) or []

            if not chunk_id:
                continue

            texts.append(text)
            meta_rows.append(
                {
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index_num,
                    "start": start,
                    "end": end,
                    "text_preview": _preview(text),  # 预览仍然给用户看正文，不用 embedding_text
                    "section_title": section_title,
                    "heading_level": heading_level,
                    "section_path": section_path,
                }
            )

        if not texts:
            manifest = {
                "file_id": file_id,
                "filename": filename,
                "sha256": sha256,
                "model_name": model_name,
                "normalize": normalize,
                "vector_dim": 0,
                "chunk_count": 0,
                "updated_at": time.time(),
                "vectors": [],
            }
            _write_json(manifest_path, manifest)

            index_items.append(
                {
                    "file_id": file_id,
                    "filename": filename,
                    "sha256": sha256,
                    "chunk_count": 0,
                    "vector_count": 0,
                    "record_path": str(manifest_path.relative_to(sandbox_root)),
                    "updated_at": manifest["updated_at"],
                }
            )
            continue

        vectors = embed_texts(
            texts=texts,
            model_name=model_name,
            normalize=normalize,
        )

        if vectors.ndim != 2:
            raise ValueError("embedding output must be 2D")

        dim = int(vectors.shape[1])
        if dim <= 0:
            raise ValueError("invalid vector_dim")

        vector_dim = dim

        manifest_vectors: List[Dict[str, Any]] = []

        for row, vec in zip(meta_rows, vectors):
            chunk_id = row["chunk_id"]
            vector_path = vectors_dir / f"{chunk_id}.npy"
            np.save(vector_path, vec.astype(np.float32))

            manifest_vectors.append(
                {
                    "chunk_id": chunk_id,
                    "chunk_index": row["chunk_index"],
                    "vector_path": str(vector_path.relative_to(sandbox_root)),
                    "start": row["start"],
                    "end": row["end"],
                    "text_preview": row["text_preview"],
                    "section_title": row.get("section_title", ""),
                    "heading_level": row.get("heading_level", 0),
                    "section_path": row.get("section_path", []),
                }
            )

        manifest = {
            "file_id": file_id,
            "filename": filename,
            "sha256": sha256,
            "model_name": model_name,
            "normalize": normalize,
            "vector_dim": dim,
            "chunk_count": len(manifest_vectors),
            "updated_at": time.time(),
            "vectors": manifest_vectors,
        }

        _write_json(manifest_path, manifest)

        total_vectors += len(manifest_vectors)
        index_items.append(
            {
                "file_id": file_id,
                "filename": filename,
                "sha256": sha256,
                "chunk_count": len(manifest_vectors),
                "vector_count": len(manifest_vectors),
                "record_path": str(manifest_path.relative_to(sandbox_root)),
                "updated_at": manifest["updated_at"],
            }
        )

    vector_index = {
        "version": "m2.5.2-v2",
        "updated_at": time.time(),
        "model_name": model_name,
        "normalize": normalize,
        "vector_dim": vector_dim,
        "stats": {
            "files_total": len(chunk_items),
            "created": created,
            "rebuilt": rebuilt,
            "skipped": skipped,
            "total_vectors": total_vectors,
        },
        "items": index_items,
    }

    _write_json(artifacts_dir / "vector_index.json", vector_index)

    return {
        "ok": True,
        "files_total": len(chunk_items),
        "created": created,
        "rebuilt": rebuilt,
        "skipped": skipped,
        "total_vectors": total_vectors,
        "vector_dim": vector_dim,
        "model_name": model_name,
        "normalize": normalize,
        "vector_index_path": "artifacts/vector_index.json",
    }


TOOL = ToolSpec(
    name="knowledge_build_embeddings",
    handler=_handler,
    risk="medium",
    description="Build dense vector embeddings from chunk records for semantic retrieval.",
    args_schema={
        "type": "object",
        "properties": {
            "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
            "model_name": {"type": "string"},
            "normalize": {"type": "boolean"},
            "max_chunks_per_file": {"type": "integer", "minimum": 1, "maximum": 100000},
            "force": {"type": "boolean"},
        },
    },
)