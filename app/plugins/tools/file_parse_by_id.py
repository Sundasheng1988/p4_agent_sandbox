from __future__ import annotations

import os
from typing import Any, Dict

from app.tools.spec import ToolSpec

def _read_txt_bytes(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")

async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    file_id = str(args["file_id"])
    max_chars = int(args.get("max_chars", 20000))

    rec = await ctx.store.get_file(file_id)
    if not rec:
        raise ValueError("file not found")

    raw_path = os.path.abspath(os.path.expanduser(os.path.join(ctx.sandbox_root, rec["rel_dir"], rec["raw_name"])))
    if not raw_path.startswith(ctx.sandbox_root):
        raise ValueError("path out of sandbox")

    ext = (rec.get("ext") or "").lower()

    # --- TXT ---
    if ext in ("txt", "md", "log"):
        with open(raw_path, "rb") as f:
            data = f.read()
        text = _read_txt_bytes(data)

        out = text[:max_chars]
        return {
            "file_id": file_id,
            "ext": ext,
            "text": out,
            "stats": {
                "chars": len(text),
                "lines": text.count("\n") + (1 if text else 0),
            },
        }

    # --- PDF ---
    if ext == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(raw_path)
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts)

        out = text[:max_chars]
        return {
            "file_id": file_id,
            "ext": ext,
            "text": out,
            "stats": {
                "pages": len(reader.pages),
                "chars": len(text),
                "lines": text.count("\n") + (1 if text else 0),
            },
        }

    # --- DOCX ---
    if ext == "docx":
        import docx

        d = docx.Document(raw_path)
        paras = [p.text for p in d.paragraphs if p.text and p.text.strip()]
        text = "\n".join(paras)

        out = text[:max_chars]
        return {
            "file_id": file_id,
            "ext": ext,
            "text": out,
            "stats": {
                "paragraphs": len(paras),
                "chars": len(text),
                "lines": text.count("\n") + (1 if text else 0),
            },
        }

    raise ValueError(f"unsupported ext: {ext}")

TOOL = ToolSpec(
    name="file_parse_by_id",
    handler=_handler,
    risk="low",
    description="Parse uploaded file (txt/pdf/docx) into normalized text by file_id.",
    args_schema={
        "type": "object",
        "properties": {
            "file_id": {"type": "string"},
            "max_chars": {"type": "integer"},
        },
        "required": ["file_id"],
    },
)