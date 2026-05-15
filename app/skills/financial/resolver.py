# app/skills/financial/resolver.py
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def normalize_text(text: Any) -> str:
    return str(text or "").strip().lower()


def parse_financial_query(user_input: str) -> Dict[str, Optional[str]]:
    q = normalize_text(user_input)

    year = None
    period = None

    year_match = re.search(r"(20\d{2})", q)
    if year_match:
        year = year_match.group(1)

    if any(k in q for k in ["一季度", "第一季度", "q1", "1季度"]):
        period = "Q1"
    elif any(k in q for k in ["半年报", "半年度", "中报", "q2"]):
        period = "H1"
    elif any(k in q for k in ["三季度", "第三季度", "q3"]):
        period = "Q3"
    elif any(k in q for k in ["年报", "年度报告", "年度财报"]):
        period = "A"

    noise_words = [
        "分析", "帮我", "请", "一下", "财报", "财务报告", "财务分析",
        "报告", "年报", "年度报告", "一季度", "第一季度", "季度",
        "半年报", "半年度", "中报", "三季度", "第三季度",
        "2024", "2025", "2026", "2027",
        "q1", "q2", "q3", "q4",
        "的",
    ]

    company_query = q
    for w in noise_words:
        company_query = company_query.replace(w, "")

    company_query = company_query.strip()

    return {
        "company_query": company_query or None,
        "year": year,
        "period": period,
    }


def infer_period_from_filename(filename: str) -> Optional[str]:
    name = normalize_text(filename)

    if any(k in name for k in ["一季度", "第一季度", "q1", "1季度"]):
        return "Q1"
    if any(k in name for k in ["半年报", "半年度", "中报", "q2"]):
        return "H1"
    if any(k in name for k in ["三季度", "第三季度", "q3"]):
        return "Q3"
    if any(k in name for k in ["年报", "年度报告", "年度"]):
        return "A"

    return None


def infer_year_from_filename(filename: str) -> Optional[str]:
    m = re.search(r"(20\d{2})", filename)
    if m:
        return m.group(1)
    return None


def score_financial_file(
    *,
    row: Dict[str, Any],
    query: Dict[str, Optional[str]],
) -> int:
    filename = normalize_text(row.get("filename", ""))
    ext = normalize_text(row.get("ext", ""))

    if ext != "pdf":
        return -999

    score = 0

    company_query = query.get("company_query")
    year = query.get("year")
    period = query.get("period")

    if company_query:
        if company_query in filename:
            score += 80
        else:
            # 简单简称匹配：只要用户输入中的连续中文片段出现在文件名中，也给分
            for token in re.findall(r"[\u4e00-\u9fa5]{2,}", company_query):
                if token in filename:
                    score += 40

    file_year = infer_year_from_filename(filename)
    if year and file_year == year:
        score += 40
    elif year and file_year and file_year != year:
        score -= 30

    file_period = infer_period_from_filename(filename)
    if period and file_period == period:
        score += 40
    elif period and file_period and file_period != period:
        score -= 30

    # 没指定公司时，不要让任意 PDF 高分
    if not company_query and not year and not period:
        score += 1

    return score


def resolve_financial_pdf(
    *,
    rows: List[Dict[str, Any]],
    sandbox_root: str,
    user_input: str,
) -> Dict[str, Any]:
    query = parse_financial_query(user_input)

    candidates = []

    for row in rows:
        file_id = str(row.get("file_id") or "")
        if not file_id:
            continue

        pdf_path = Path(sandbox_root) / "uploads" / file_id / "raw.pdf"
        if not pdf_path.exists():
            continue

        score = score_financial_file(row=row, query=query)

        if score <= 0:
            continue

        candidates.append({
            "row": row,
            "score": score,
            "pdf_path": pdf_path,
        })

    if not candidates:
        return {
            "ok": False,
            "error": "no matched financial pdf found",
            "query": query,
        }

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["row"].get("created_at", 0),
        ),
        reverse=True,
    )

    best = candidates[0]
    row = best["row"]
    file_id = str(row.get("file_id"))

    return {
        "ok": True,
        "file_id": file_id,
        "filename": row.get("filename"),
        "pdf_path": str(best["pdf_path"]),
        "parse_dir": str(Path(sandbox_root) / "artifacts" / "financial_parsed" / file_id),
        "match_score": best["score"],
        "query": query,
        "candidates": [
            {
                "file_id": c["row"].get("file_id"),
                "filename": c["row"].get("filename"),
                "score": c["score"],
            }
            for c in candidates[:5]
        ],
    }