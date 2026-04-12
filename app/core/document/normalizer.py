from __future__ import annotations

import re
from typing import List

from app.core.document.schema import DocumentBlock, ParsedDocument


_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def clean_text(text: str) -> str:
    text = (text or "").replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()


def infer_title(filename: str, blocks: List[DocumentBlock]) -> str:
    for block in blocks:
        if block.block_type == "heading" and block.text.strip():
            return block.text.strip()
    return filename


def normalize_document(doc: ParsedDocument) -> ParsedDocument:
    normalized_blocks: List[DocumentBlock] = []

    for idx, block in enumerate(doc.blocks):
        text = clean_text(block.text)
        if not text and block.block_type != "image":
            continue

        normalized_blocks.append(
            DocumentBlock(
                block_id=block.block_id,
                block_type=block.block_type,
                text=text,
                order=idx,
                level=block.level,
                page_num=block.page_num,
                section_path=list(block.section_path or []),
                meta=dict(block.meta or {}),
            )
        )

    return ParsedDocument(
        file_id=doc.file_id,
        filename=doc.filename,
        file_type=doc.file_type,
        title=doc.title or infer_title(doc.filename, normalized_blocks),
        blocks=normalized_blocks,
        meta=dict(doc.meta or {}),
    )