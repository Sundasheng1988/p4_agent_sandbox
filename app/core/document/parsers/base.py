from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.core.document.schema import ParsedDocument


class BaseDocumentParser(ABC):
    @abstractmethod
    def parse(self, file_path: Path, file_id: str, filename: str) -> ParsedDocument:
        raise NotImplementedError