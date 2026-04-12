from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


BLOCK_TYPES = {
    "heading",
    "paragraph",
    "table",
    "list",
    "image",
    "code",
    "quote",
}


@dataclass
class DocumentBlock:
    block_id: str
    block_type: str
    text: str
    order: int

    level: Optional[int] = None
    page_num: Optional[int] = None
    section_path: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def normalized_text(self) -> str:
        return (self.text or "").strip()


@dataclass
class ParsedDocument:
    file_id: str
    filename: str
    file_type: str
    title: Optional[str]
    blocks: List[DocumentBlock] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_id": self.file_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "title": self.title,
            "meta": self.meta,
            "blocks": [b.to_dict() for b in self.blocks],
        }

    @property
    def block_count(self) -> int:
        return len(self.blocks)


@dataclass
class KnowledgeChunk:
    chunk_id: str
    file_id: str
    filename: str
    file_type: str
    text: str
    snippet: str
    chunk_index: int

    block_ids: List[str] = field(default_factory=list)
    page_range: List[int] = field(default_factory=list)
    section_path: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)