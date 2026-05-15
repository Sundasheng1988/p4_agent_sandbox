#knowledge_build_chunks.py
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.chunking import build_chunks_for_text
from app.tools.spec import ToolSpec
from app.core.document.table_chunker import build_table_row_chunks




def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")

def _load_preferred_text_source(
    *,
    sandbox_root: Path,
    file_id: str,
    fallback_text: str,
) -> tuple[str, Dict[str, Any]]:
    """
    优先使用财报解析后的 report.md。
    如果不存在，则回退到原始 parse_text_by_id 的结果。
    """
    financial_report_md = (
        sandbox_root
        / "artifacts"
        / "financial_parsed"
        / file_id
        / "report.md"
    )

    if financial_report_md.exists():
        text = financial_report_md.read_text(encoding="utf-8", errors="replace")
        return text, {
            "text_source": "financial_parsed_report_md",
            "text_source_path": str(financial_report_md.relative_to(sandbox_root)),
        }

    return fallback_text, {
        "text_source": "file_service_parse_text_by_id",
        "text_source_path": None,
    }

def _load_document_structure(
    *,
    sandbox_root: Path,
    file_id: str,
) -> List[Dict[str, Any]]:
    p = (
        sandbox_root
        / "artifacts"
        / "financial_parsed"
        / file_id
        / "document_structure.json"
    )

    if not p.exists():
        return []

    try:
        data = _load_json(p)
    except Exception:
        return []

    sections = data.get("sections", [])
    if not isinstance(sections, list):
        return []

    clean = []
    for s in sections:
        if not isinstance(s, dict):
            continue

        start = s.get("start")
        end = s.get("end")

        if start is None or end is None:
            continue

        try:
            s = dict(s)
            s["start"] = int(start)
            s["end"] = int(end)
            clean.append(s)
        except Exception:
            continue

    clean.sort(key=lambda x: (int(x.get("start", 0)), int(x.get("end", 0))))
    return clean


def _find_best_section_for_chunk(
    *,
    chunk: Dict[str, Any],
    sections: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not sections:
        return None

    chunk_start = chunk.get("start")
    chunk_end = chunk.get("end")

    try:
        chunk_start = int(chunk_start)
        chunk_end = int(chunk_end)
    except Exception:
        return None

    best = None
    best_overlap = 0

    for s in sections:
        s_start = int(s.get("start", 0))
        s_end = int(s.get("end", 0))

        overlap = max(0, min(chunk_end, s_end) - max(chunk_start, s_start))

        if overlap > best_overlap:
            best_overlap = overlap
            best = s

    return best


def _attach_document_structure_metadata(
    *,
    chunks: List[Dict[str, Any]],
    sections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not chunks or not sections:
        return chunks

    enriched: List[Dict[str, Any]] = []

    for c in chunks:
        chunk = dict(c)

        # 表格 chunk 暂时不按文本 offset 绑定 section
        chunk_id = str(chunk.get("chunk_id") or "")
        text = str(chunk.get("text") or chunk.get("content") or "")

        if "_table_" in chunk_id or text.startswith("表格来源："):
            enriched.append(chunk)
            continue

        section = _find_best_section_for_chunk(
            chunk=chunk,
            sections=sections,
        )

        if section:
            chunk["section_id"] = section.get("section_id")
            chunk["section_title"] = section.get("section_title")
            chunk["section_path"] = section.get("section_path", [])
            chunk["section_type"] = section.get("section_type")
            chunk["financial_topic"] = section.get("financial_topic", [])
            chunk["section_page"] = section.get("page")
            chunk["section_start"] = section.get("start")
            chunk["section_end"] = section.get("end")

            meta = dict(chunk.get("meta") or chunk.get("metadata") or {})
            meta.update(
                {
                    "section_id": section.get("section_id"),
                    "section_title": section.get("section_title"),
                    "section_path": section.get("section_path", []),
                    "section_type": section.get("section_type"),
                    "financial_topic": section.get("financial_topic", []),
                    "section_page": section.get("page"),
                }
            )
            chunk["metadata"] = meta

        enriched.append(chunk)

    return enriched

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
        fallback_text = parsed.get("text", "") or ""

        text, text_source_info = _load_preferred_text_source(
            sandbox_root=sandbox_root,
            file_id=file_id,
            fallback_text=fallback_text,
        )

        if max_chars and len(text) > max_chars:
            text = text[:max_chars]

        file_meta = await ctx.file_service.get_meta_by_id(file_id)

        if text_source_info.get("text_source") == "financial_parsed_report_md":
            file_meta = dict(file_meta or {})
            file_meta.update(
                {
                    "domain": file_meta.get("domain") or "financial_report",
                    "file_type": "markdown",
                    "source": "financial_parsed_pdf",
                    "original_file_id": file_id,
                }
            )

        chunks = build_chunks_for_text(
            file_id=file_id,
            filename=filename,
            text=text,
            chunk_size=chunk_size,
            overlap=overlap,
            file_meta=file_meta,
        )
        
        # =========================
        # Document structure metadata
        # =========================
        document_sections = _load_document_structure(
            sandbox_root=sandbox_root,
            file_id=file_id,
        )

        if document_sections:
            chunks = _attach_document_structure_metadata(
                chunks=chunks,
                sections=document_sections,
            )

        # =========================
        # PDF table semantic chunks
        # =========================
        tables_dir = sandbox_root / "artifacts" / "financial_parsed" / file_id / "tables"

        table_chunks = build_table_row_chunks(
            file_id=file_id,
            filename=filename,
            tables_dir=tables_dir,
            source=file_meta.get("source", "upload"),
            domain=file_meta.get("domain", "general"),
            file_type="table",
        )

        if table_chunks:
            chunks.extend(table_chunks)

        record = {
            "file_id": file_id,
            "filename": filename,
            "sha256": sha256,
            "max_chars": max_chars,
            "chunk_size": chunk_size,
            "overlap": overlap,
            "source_chars": len(text),
            "chunk_count": len(chunks),
            "document_structure_count": len(document_sections) if "document_sections" in locals() else 0,
            "updated_at": time.time(),
            "chunks": chunks,
            "text_source": text_source_info.get("text_source"),
            "text_source_path": text_source_info.get("text_source_path"),
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