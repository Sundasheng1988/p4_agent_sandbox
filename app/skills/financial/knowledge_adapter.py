# knowledge_adapter.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


async def build_financial_knowledge(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
    **kwargs,
) -> Dict[str, Any]:
    """
    将财报解析后的 report.md 接入已有 Knowledge Runtime。
    注意：这里不重写 RAG，只把财报 markdown 注册成可检索材料。
    """

    inputs = state.get("collect_financial_inputs", {})
    file_id = inputs.get("file_id")
    filename = inputs.get("filename")
    parse_dir = Path(inputs.get("parse_dir", ""))
    report_md = parse_dir / "report.md"

    if not file_id:
        return {"ok": False, "error": "missing file_id"}

    if not report_md.exists():
        return {"ok": False, "error": f"report.md not found: {report_md}"}

    # 关键：这里先返回路径和元信息。
    # 后续由你已有的 knowledge_build_chunks / embeddings 工具读取这个 markdown。
    return {
        "ok": True,
        "file_id": file_id,
        "filename": filename,
        "knowledge_source_path": str(report_md),
        "domain": "financial_report",
        "file_type": "markdown",
        "source": "financial_parsed_pdf",
    }


async def register_financial_markdown(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    parse_out = state.get("parse_financial_pdf", {})
    report_md = Path(parse_out.get("report_md", ""))

    if not report_md.exists():
        return {
            "ok": False,
            "error": f"report.md not found: {report_md}",
        }

    original_inputs = state.get("collect_financial_inputs", {})
    original_filename = original_inputs.get("filename", "financial_report.pdf")

    md_filename = original_filename.rsplit(".", 1)[0] + "_parsed.md"
    data = report_md.read_bytes()

    meta = await ctx.file_service.save_upload(
        filename=md_filename,
        mime="text/markdown",
        data=data,
    )

    # 补充财报专用 metadata，供 RAG router / filter 使用
    file_id = meta.get("file_id")
    if file_id:
        meta_path = Path(sandbox_root) / "uploads" / file_id / "meta.json"

        try:
            import json

            current_meta = {}
            if meta_path.exists():
                current_meta = json.loads(meta_path.read_text(encoding="utf-8"))

            current_meta.update(
                {
                    "domain": "financial_report",
                    "file_type": "markdown",
                    "source": "financial_parsed_pdf",
                    "original_file_id": original_inputs.get("file_id"),
                    "original_filename": original_filename,
                    "derived_from": "financial_pdf_parser",
                }
            )

            meta_path.write_text(
                json.dumps(current_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            meta = current_meta

        except Exception as e:
            return {
                "ok": False,
                "error": f"failed to update financial metadata: {e}",
            }

    return {
        "ok": True,
        "registered_file": meta,
        "markdown_file_id": meta.get("file_id"),
        "markdown_filename": meta.get("filename"),
        "source_report_md": str(report_md),
        "domain": meta.get("domain"),
        "file_type": meta.get("file_type"),
        "source": meta.get("source"),
    }