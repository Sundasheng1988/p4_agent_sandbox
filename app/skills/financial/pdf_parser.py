# pdf_parser.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from app.skills.financial.document_structure import build_document_structure_from_report

import csv
import json
import fitz
import pdfplumber


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

async def parse_financial_pdf(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    

    inputs = state.get("collect_financial_inputs", {})
    pdf_path = Path(inputs.get("pdf_path", ""))

    if not pdf_path.exists():
        return {
            "ok": False,
            "error": f"pdf not found: {pdf_path}",
        }

    file_id = inputs.get("file_id", "unknown")
    parse_dir = Path(inputs.get("parse_dir", ""))

    if not str(parse_dir):
        parse_dir = Path(sandbox_root) / "artifacts" / "financial_parsed" / file_id

    tables_dir = parse_dir / "tables"

    _ensure_dir(parse_dir / "dummy.txt")
    _ensure_dir(tables_dir / "dummy.txt")

    # =========================
    # 1. 文本解析（PyMuPDF）
    # =========================
    doc = fitz.open(pdf_path)
    pages_data = []
    md_lines = []

    for i, page in enumerate(doc):
        text = page.get_text()
        pages_data.append({
            "page": i + 1,
            "text_length": len(text),
        })

        md_lines.append(f"\n\n# Page {i+1}\n\n{text}")

    report_md_path = parse_dir / "report.md"
    pages_json_path = parse_dir / "pages.json"

    report_md_path.write_text("\n".join(md_lines), encoding="utf-8")
    pages_json_path.write_text(json.dumps(pages_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # =========================
    # 2. 表格解析（pdfplumber）
    # =========================
    table_index = []
    table_count = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            tables = page.extract_tables()

            if not tables:
                continue

            for t_idx, table in enumerate(tables):
                table_count += 1
                filename = f"page_{page_idx+1}_table_{t_idx+1}.csv"
                csv_path = tables_dir / filename
                json_path = tables_dir / filename.replace(".csv", ".json")

                # 写 CSV
                import csv
                with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                    writer = csv.writer(f)
                    for row in table:
                        writer.writerow(row)

                # 写 JSON
                json_path.write_text(
                    json.dumps(table, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )

                table_index.append({
                    "page": page_idx + 1,
                    "table_id": t_idx + 1,
                    "csv": str(csv_path),
                    "json": str(json_path),
                })

    table_index_path = parse_dir / "table_index.json"
    table_index_path.write_text(
        json.dumps(table_index, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
        # =========================
    # 3. 文档结构识别
    # =========================
    document_structure_path = parse_dir / "document_structure.json"

    document_structure = build_document_structure_from_report(
        report_md_path=report_md_path,
        output_path=document_structure_path,
        file_id=file_id,
        filename=inputs.get("filename", ""),
        use_llm_heading_judge=False,
        llm_model_name="qwen2.5:7b-instruct",
    )

    return {
        "ok": True,
        "parse_dir": str(parse_dir),
        "report_md": str(report_md_path),
        "pages_json": str(pages_json_path),
        "tables_dir": str(tables_dir),
        "table_index": str(table_index_path),
        "table_count": table_count,
        "document_structure": str(document_structure_path),
        "document_structure_count": document_structure.get("section_count", 0),
    }