from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from app.core.document.schema import DocumentBlock, ParsedDocument


class DocumentStore:
    def __init__(self, artifacts_root: Path) -> None:
        self.artifacts_root = artifacts_root
        self.parsed_dir = self.artifacts_root / "parsed"
        self.parsed_dir.mkdir(parents=True, exist_ok=True)

    def get_parsed_path(self, file_id: str) -> Path:
        return self.parsed_dir / f"{file_id}.parsed.json"

    def save(self, doc: ParsedDocument) -> Path:
        path = self.get_parsed_path(doc.file_id)
        with path.open("w", encoding="utf-8") as f:
            json.dump(doc.to_dict(), f, ensure_ascii=False, indent=2)
        return path

    def load(self, file_id: str) -> Optional[ParsedDocument]:
        path = self.get_parsed_path(file_id)
        if not path.exists():
            return None

        data = json.loads(path.read_text(encoding="utf-8"))
        blocks_data = data.get("blocks", [])
        blocks: List[DocumentBlock] = [DocumentBlock(**item) for item in blocks_data]

        return ParsedDocument(
            file_id=data["file_id"],
            filename=data["filename"],
            file_type=data["file_type"],
            title=data.get("title"),
            blocks=blocks,
            meta=data.get("meta", {}),
        )

    def exists(self, file_id: str) -> bool:
        return self.get_parsed_path(file_id).exists()