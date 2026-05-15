# table_chunker.py

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Dict, List


def _clean(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _normalize_cell(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").replace("\n", "").strip())


def _normalize_header(value: Any) -> str:
    text = str(value or "").replace("\n", "").strip()
    text = re.sub(r"\s+", "", text)
    return text


def _merge_headers(header1: List[str], header2: List[str]) -> List[str]:
    headers: List[str] = []
    max_len = max(len(header1), len(header2))

    for i in range(max_len):
        h1 = _normalize_header(header1[i]) if i < len(header1) else ""
        h2 = _normalize_header(header2[i]) if i < len(header2) else ""

        if h1 and h2 and h1 != h2:
            headers.append(f"{h1}-{h2}")
        else:
            headers.append(h1 or h2 or f"列{i}")

    return headers


def _detect_header_rows(rows: List[List[str]]) -> int:
    """
    通用规则：
    - 默认前 2 行作为表头，适合复杂 PDF 表格；
    - 如果第 1 行明显就是单级表头，例如第一列是“项目/名称/指标”，也允许只用 1 行；
    - 为了兼容你现有财报表格，这里仍优先保留 2 行表头。
    """
    if len(rows) < 2:
        return 1

    first = [_normalize_header(x) for x in rows[0]]
    second = [_normalize_header(x) for x in rows[1]]

    first_text = "".join(first)
    second_text = "".join(second)

    # 第二行像“金额/比例/说明”这类子表头时，用两级表头
    second_header_markers = [
        "金额",
        "比例",
        "占比",
        "说明",
        "原因",
        "期末",
        "期初",
        "本期",
        "上期",
        "增减",
        "变动",
    ]

    if any(k in second_text for k in second_header_markers):
        return 2

    # 第一行已经是完整单级表头时，用一行表头
    first_header_markers = [
        "项目",
        "名称",
        "指标",
        "类别",
        "类型",
        "内容",
        "说明",
        "金额",
        "日期",
        "状态",
    ]

    if any(k in first_text for k in first_header_markers):
        return 1

    return 2


def _build_headers(rows: List[List[str]], header_row_count: int) -> List[str]:
    if header_row_count <= 1:
        return [
            _normalize_header(x) or f"列{i}"
            for i, x in enumerate(rows[0])
        ]

    header1 = rows[0]
    header2 = rows[1] if len(rows) > 1 else []
    return _merge_headers(header1, header2)


def _pick_row_entity(row: List[str]) -> str:
    """
    通用表格行对象：
    - 默认取第一列非空内容；
    - 不叫 metric，避免财报专用。
    """
    for cell in row:
        value = _normalize_cell(cell)
        if value:
            return value
    return ""


def _row_to_fields(row: List[str], headers: List[str]) -> Dict[str, str]:
    fields: Dict[str, str] = {}

    for i, cell in enumerate(row):
        key = headers[i] if i < len(headers) else f"列{i}"
        value = _normalize_cell(cell)

        if not key or not value:
            continue

        fields[key] = value

    return fields


def _render_table_row_text(
    *,
    filename: str,
    page_no: int | None,
    table_no: int | None,
    row_entity: str,
    fields: Dict[str, str],
) -> str:
    lines = [
        f"表格来源：{filename}，第{page_no}页，第{table_no}个表格。",
        f"表格行对象：{row_entity}。",
    ]

    for key, value in fields.items():
        lines.append(f"{key}：{value}")

    return "\n".join(lines)


def build_table_row_chunks(
    *,
    file_id: str,
    filename: str,
    tables_dir: Path,
    source: str = "pdf_table",
    domain: str = "general",
    file_type: str = "pdf",
) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []

    if not tables_dir.exists():
        return chunks

    chunk_index = 0

    for csv_path in sorted(tables_dir.glob("*.csv")):
        m = re.search(r"page_(\d+)_table_(\d+)\.csv", csv_path.name)
        page_no = int(m.group(1)) if m else None
        table_no = int(m.group(2)) if m else None

        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.reader(f))

        rows = [
            [str(cell or "") for cell in row]
            for row in rows
            if row and any(_clean(cell) for cell in row)
        ]

        if len(rows) < 2:
            continue

        header_row_count = _detect_header_rows(rows)
        headers = _build_headers(rows, header_row_count)
        data_rows = rows[header_row_count:]

        for row_no, row in enumerate(data_rows, start=header_row_count + 1):
            if not row or not any(_clean(x) for x in row):
                continue

            row_entity = _pick_row_entity(row)
            if not row_entity:
                continue

            fields = _row_to_fields(row, headers)
            if not fields:
                continue

            text = _render_table_row_text(
                filename=filename,
                page_no=page_no,
                table_no=table_no,
                row_entity=row_entity,
                fields=fields,
            )

            chunk_id = f"{file_id}_table_{page_no}_{table_no}_{row_no}"

            chunks.append(
                {
                    "file_id": file_id,
                    "filename": filename,
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "text": text,
                    "content": text,
                    "snippet": text[:500],
                    "page": page_no,
                    "table": table_no,
                    "row": row_no,
                    "domain": domain,
                    "file_type": file_type,
                    "source": source,
                    "chunk_type": "table_row",
                    "row_entity": row_entity,
                    "fields": fields,
                    "metadata": {
                        "chunk_type": "table_row",
                        "kind": "table_row",
                        "page": page_no,
                        "table": table_no,
                        "row": row_no,
                        "csv_path": str(csv_path),
                        "row_entity": row_entity,
                        "column_fields": list(fields.keys()),
                        "fields": fields,
                        "columns": headers,

                        # 兼容旧代码，暂时保留
                        "metric": row_entity,
                        "row_data": fields,
                    },
                }
            )

            chunk_index += 1

    return chunks