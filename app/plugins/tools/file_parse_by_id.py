from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from app.core.document.parser_service import DocumentParserService
from app.tools.spec import ToolSpec


def _read_txt_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def _safe_get_sandbox_root(ctx) -> str:
    sandbox_root = getattr(ctx, "sandbox_root", None)
    if sandbox_root:
        return os.path.abspath(os.path.expanduser(str(sandbox_root)))

    config = getattr(ctx, "config", None)
    if config and getattr(config, "sandbox_root", None):
        return os.path.abspath(os.path.expanduser(str(config.sandbox_root)))

    raise ValueError("sandbox_root not found in ctx")


def _safe_get_artifacts_root(ctx) -> Path:
    config = getattr(ctx, "config", None)
    if config and getattr(config, "artifacts_root", None):
        return Path(config.artifacts_root)

    sandbox_root = _safe_get_sandbox_root(ctx)
    return Path(sandbox_root).parent / "artifacts"


def _build_preview_text_from_blocks(blocks: list[dict], max_chars: int) -> str:
    parts: list[str] = []
    total = 0

    for block in blocks:
        text = (block.get("text") or "").strip()
        if not text:
            continue

        remain = max_chars - total
        if remain <= 0:
            break

        piece = text[:remain]
        parts.append(piece)
        total += len(piece)

        if total < max_chars:
            parts.append("\n\n")
            total += 2

    return "".join(parts)[:max_chars]


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    file_id = str(args["file_id"])
    max_chars = int(args.get("max_chars", 20000))

    rec = await ctx.store.get_file(file_id)
    if not rec:
        raise ValueError("file not found")

    sandbox_root = _safe_get_sandbox_root(ctx)
    artifacts_root = _safe_get_artifacts_root(ctx)

    raw_path = os.path.abspath(
        os.path.expanduser(
            os.path.join(sandbox_root, rec["rel_dir"], rec["raw_name"])
        )
    )
    if not raw_path.startswith(sandbox_root):
        raise ValueError("path out of sandbox")

    filename = rec.get("filename") or rec.get("raw_name") or file_id
    ext = (rec.get("ext") or "").lower().lstrip(".")

    # 兼容旧类型：txt / log 仍按纯文本读取
    if ext in ("txt", "log"):
        with open(raw_path, "rb") as f:
            data = f.read()
        text = _read_txt_bytes(data)
        out = text[:max_chars]

        return {
            "file_id": file_id,
            "filename": filename,
            "file_type": ext,
            "title": filename,
            "text": out,
            "stats": {
                "chars": len(text),
                "lines": text.count("\n") + (1 if text else 0),
            },
        }

    # 新逻辑：md / pdf / docx 走统一文档解析
    if ext in ("md", "markdown", "pdf", "docx"):
        parser_service = DocumentParserService(artifacts_root=artifacts_root)
        doc = parser_service.parse_file(
            file_path=Path(raw_path),
            file_id=file_id,
            filename=filename,
            ext=ext,
            save=True,
        )

        preview_text = _build_preview_text_from_blocks(
            blocks=[b.to_dict() for b in doc.blocks],
            max_chars=max_chars,
        )

        parsed_path = parser_service.store.get_parsed_path(file_id)

        page_nums = sorted(
            {
                b.page_num
                for b in doc.blocks
                if getattr(b, "page_num", None) is not None
            }
        )

        block_type_counts: Dict[str, int] = {}
        for b in doc.blocks:
            block_type_counts[b.block_type] = block_type_counts.get(b.block_type, 0) + 1

        return {
            "file_id": file_id,
            "filename": filename,
            "file_type": doc.file_type,
            "title": doc.title,
            "text": preview_text,
            "parsed_path": str(parsed_path),
            "block_count": doc.block_count,
            "stats": {
                "chars": sum(len((b.text or "")) for b in doc.blocks),
                "pages": len(page_nums) if page_nums else None,
                "block_types": block_type_counts,
            },
        }

    raise ValueError(f"unsupported ext: {ext}")


TOOL = ToolSpec(
    name="file_parse_by_id",
    handler=_handler,
    risk="low",
    description="Parse uploaded file into structured document blocks by file_id.",
    args_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "max_chars": {"type": "integer"},
        },
        "required": ["file_id"],
    },
)