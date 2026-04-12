from __future__ import annotations

from typing import List

from app.core.document.schema import DocumentBlock, KnowledgeChunk, ParsedDocument


class ChunkBuilder:
    def __init__(self, target_chars: int = 900, max_chars: int = 1400) -> None:
        self.target_chars = target_chars
        self.max_chars = max_chars

    def build(self, doc: ParsedDocument) -> List[KnowledgeChunk]:
        chunks: List[KnowledgeChunk] = []
        current_blocks: List[DocumentBlock] = []
        current_texts: List[str] = []
        chunk_index = 0

        def flush() -> None:
            nonlocal chunk_index, current_blocks, current_texts
            if not current_blocks:
                return

            text = "\n\n".join(t for t in current_texts if t.strip()).strip()
            if not text:
                current_blocks = []
                current_texts = []
                return

            pages = sorted(
                {
                    b.page_num
                    for b in current_blocks
                    if b.page_num is not None
                }
            )
            section_path = current_blocks[-1].section_path if current_blocks else []

            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"{doc.file_id}_{chunk_index:04d}",
                    file_id=doc.file_id,
                    filename=doc.filename,
                    file_type=doc.file_type,
                    text=text,
                    snippet=text[:240],
                    chunk_index=chunk_index,
                    block_ids=[b.block_id for b in current_blocks],
                    page_range=pages,
                    section_path=list(section_path),
                    meta={},
                )
            )

            chunk_index += 1
            current_blocks = []
            current_texts = []

        for block in doc.blocks:
            block_text = block.normalized_text()
            if not block_text and block.block_type != "image":
                continue

            if block.block_type in {"table", "image"}:
                flush()
                current_blocks = [block]
                current_texts = [block_text or "[IMAGE]"]
                flush()
                continue

            if block.block_type == "heading":
                flush()
                current_blocks = [block]
                current_texts = [block_text]
                continue

            candidate_parts = current_texts + [block_text]
            candidate = "\n\n".join(candidate_parts).strip()

            same_section = (
                not current_blocks
                or current_blocks[-1].section_path == block.section_path
            )

            if current_blocks and (len(candidate) > self.max_chars or not same_section):
                flush()

            current_blocks.append(block)
            current_texts.append(block_text)

            if len("\n\n".join(current_texts)) >= self.target_chars:
                flush()

        flush()
        return chunks