from __future__ import annotations

from pathlib import Path

from app.core.document.parsers.docx_parser import DocxParser
from app.core.document.parsers.markdown_parser import MarkdownParser
from app.core.document.parsers.pdf_parser import PdfParser
from app.core.document.schema import ParsedDocument
from app.core.document.store import DocumentStore


class DocumentParserService:
    def __init__(self, artifacts_root: Path) -> None:
        self.store = DocumentStore(artifacts_root)
        self.parsers = {
            "md": MarkdownParser(),
            "markdown": MarkdownParser(),
            "docx": DocxParser(),
            "pdf": PdfParser(),
        }

    def parse_file(
        self,
        file_path: Path,
        file_id: str,
        filename: str,
        ext: str,
        save: bool = True,
    ) -> ParsedDocument:
        normalized_ext = ext.lower().lstrip(".")
        parser = self.parsers.get(normalized_ext)
        if parser is None:
            raise ValueError(f"Unsupported file type: {ext}")

        doc = parser.parse(file_path=file_path, file_id=file_id, filename=filename)
        if save:
            self.store.save(doc)
        return doc