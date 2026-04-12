from __future__ import annotations

from pathlib import Path
from typing import List

from app.core.document.normalizer import normalize_document
from app.core.document.parsers.base import BaseDocumentParser
from app.core.document.schema import DocumentBlock, ParsedDocument


class MarkdownParser(BaseDocumentParser):
    def parse(self, file_path: Path, file_id: str, filename: str) -> ParsedDocument:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()

        blocks: List[DocumentBlock] = []
        order = 0
        paragraph_buffer: List[str] = []
        code_buffer: List[str] = []
        in_code_block = False
        section_stack: List[str] = []

        def next_block_id() -> str:
            return f"{file_id}_b{len(blocks):04d}"

        def flush_paragraph() -> None:
            nonlocal order
            if not paragraph_buffer:
                return

            para_text = "\n".join(paragraph_buffer).strip()
            if para_text:
                block_type = "list" if _looks_like_list(para_text) else "paragraph"
                blocks.append(
                    DocumentBlock(
                        block_id=next_block_id(),
                        block_type=block_type,
                        text=para_text,
                        order=order,
                        section_path=list(section_stack),
                    )
                )
                order += 1
            paragraph_buffer.clear()

        def flush_code() -> None:
            nonlocal order
            if not code_buffer:
                return
            code_text = "\n".join(code_buffer).strip("\n")
            blocks.append(
                DocumentBlock(
                    block_id=next_block_id(),
                    block_type="code",
                    text=code_text,
                    order=order,
                    section_path=list(section_stack),
                )
            )
            order += 1
            code_buffer.clear()

        for raw_line in lines:
            line = raw_line.rstrip("\n")
            stripped = line.strip()

            if stripped.startswith("```"):
                flush_paragraph()
                if in_code_block:
                    flush_code()
                    in_code_block = False
                else:
                    in_code_block = True
                continue

            if in_code_block:
                code_buffer.append(line)
                continue

            if not stripped:
                flush_paragraph()
                continue

            if stripped.startswith("#"):
                flush_paragraph()
                level = len(stripped) - len(stripped.lstrip("#"))
                title = stripped[level:].strip()
                if not title:
                    continue

                section_stack = section_stack[: max(level - 1, 0)]
                section_stack.append(title)

                blocks.append(
                    DocumentBlock(
                        block_id=next_block_id(),
                        block_type="heading",
                        text=title,
                        order=order,
                        level=level,
                        section_path=list(section_stack),
                    )
                )
                order += 1
                continue

            paragraph_buffer.append(line)

        flush_paragraph()
        flush_code()

        doc = ParsedDocument(
            file_id=file_id,
            filename=filename,
            file_type=_infer_markdown_type(filename),
            title=None,
            blocks=blocks,
            meta={},
        )
        return normalize_document(doc)


def _looks_like_list(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    hit = 0
    for line in lines:
        if line.startswith(("- ", "* ", "+ ")):
            hit += 1
            continue
        if len(line) >= 3 and line[0].isdigit() and line[1:3] in {". ", ") "}:
            hit += 1
    return hit >= max(1, len(lines) // 2)


def _infer_markdown_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".markdown"):
        return "markdown"
    return "md"