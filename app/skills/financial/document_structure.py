# document_structure.py
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


_PAGE_RE = re.compile(r"^# Page\s+(\d+)\s*$", re.IGNORECASE)

_LEVEL1_RE = re.compile(r"^第[一二三四五六七八九十百]+节\s*.+$")
_LEVEL2_RE = re.compile(r"^[一二三四五六七八九十]+、\s*.+$")
_LEVEL3_RE = re.compile(r"^\d{1,3}、\s*[\u4e00-\u9fffA-Za-z].+$")


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip())


def _rule_detect_heading(line: str) -> tuple[bool, int, str]:
    text = _normalize_line(line)

    if not text:
        return False, 0, "empty"

    if _PAGE_RE.match(text):
        return False, 0, "page_marker"

    # 目录点线不是标题
    if "." * 5 in text or "……" in text:
        return False, 0, "toc_line"

    # 明显是页眉：公司名 + 年报全文
    if "年度报告全文" in text and len(text) <= 40:
        return False, 0, "running_header"

    # 太长的“一、xxx。”多数是列表句，不是标题
    if len(text) > 60:
        return False, 0, "too_long"

    # 句号结尾多数是完整句或列表项
    if text.endswith(("。", "；", "，", "、")):
        return False, 0, "sentence_like"
    
    if re.search(r"\d{4}\s*年|\d+\.\d+|亿元|万元|同比|增长|下降", text):
        if len(text) > 28:
            return False, 0, "numeric_sentence_like"

    # “1、风险分析：公司基于……”这种是正文说明，不是标题
    if "：" in text or ":" in text:
        if len(text) > 25:
            return False, 0, "colon_sentence_like"

    if _LEVEL1_RE.match(text):
        return True, 1, "cn_report_section"

    if _LEVEL2_RE.match(text):
        return True, 2, "cn_major_heading"

    if _LEVEL3_RE.match(text):
        return True, 3, "cn_numbered_heading"

    return False, 0, "not_heading"


def _build_llm_heading_prompt(candidates: List[Dict[str, Any]]) -> str:
    simple_items = [
        {
            "idx": i,
            "page": c.get("page"),
            "text": c.get("text"),
            "rule_level": c.get("rule_level"),
            "prev": c.get("prev", ""),
            "next": c.get("next", ""),
        }
        for i, c in enumerate(candidates)
    ]

    return f"""
你是一个中文年报 PDF 文档结构识别助手。

你的任务：判断候选文本是否是真正的“章节标题”，而不是正文、目录项、列表项、表格行或页眉页脚。

判断规则：
1. “第一节/第二节/第三节/第八节”等通常是一级标题。
2. “一、报告期内公司从事的主要业务”“四、主营业务分析”等通常是二级标题。
3. “1、资产构成重大变动情况”“3、公司面临的风险及应对措施”等通常是三级标题。
4. 如果文本是完整句子、备查文件列表、表格内容、目录点线、页眉页脚，应判断为 false。
5. 不要凭常识扩展，只根据候选文本和上下文判断。
6. 只输出 JSON，不要输出解释文字。

输出格式必须是：
{{
  "items": [
    {{"idx": 0, "is_heading": true, "level": 1, "reason": "简短原因"}},
    {{"idx": 1, "is_heading": false, "level": 0, "reason": "简短原因"}}
  ]
}}

候选列表：
{json.dumps(simple_items, ensure_ascii=False, indent=2)}
""".strip()


def _parse_llm_heading_result(raw: str) -> Dict[int, Dict[str, Any]]:
    text = str(raw or "").strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except Exception:
        return {}

    items = data.get("items", []) if isinstance(data, dict) else []
    result: Dict[int, Dict[str, Any]] = {}

    for item in items:
        if not isinstance(item, dict):
            continue

        try:
            idx = int(item.get("idx"))
        except Exception:
            continue

        result[idx] = {
            "is_heading": bool(item.get("is_heading")),
            "level": int(item.get("level") or 0),
            "reason": str(item.get("reason") or ""),
        }

    return result


def _judge_candidates_with_llm(
    *,
    candidates: List[Dict[str, Any]],
    model_name: str,
    batch_size: int = 40,
    timeout: int = 120,
) -> Dict[int, Dict[str, Any]]:
    from app.core.llm_client import generate_with_ollama

    final: Dict[int, Dict[str, Any]] = {}

    for start in range(0, len(candidates), batch_size):
        batch = candidates[start:start + batch_size]
        prompt = _build_llm_heading_prompt(batch)

        try:
            out = generate_with_ollama(
                prompt=prompt,
                model_name=model_name,
                timeout=timeout,
            )
            parsed = _parse_llm_heading_result(out.get("response", ""))
        except Exception:
            parsed = {}

        for local_idx, judge in parsed.items():
            final[start + local_idx] = judge

    return final


def _classify_section_type(title: str, path: List[str]) -> str:
    text = " / ".join(path + [title])

    if "主要财务指标" in text:
        return "key_financial_metrics"

    if "管理层讨论与分析" in text:
        if "主营业务分析" in text:
            return "business_analysis"
        if "资产及负债状况分析" in text or "资产构成重大变动情况" in text:
            return "balance_sheet_analysis"
        if "公司面临的风险" in text or "风险及应对" in text:
            return "risk_analysis"
        if "未来发展" in text or "经营计划" in text or "展望" in text:
            return "future_outlook"
        return "management_discussion"

    if "财务报告" in text:
        if any(k in text for k in ["货币资金", "应收账款", "预付款项", "存货", "合同资产", "应付账款", "合同负债"]):
            return "financial_statement_note"
        return "financial_report"

    return "general"


def _infer_financial_topics(title: str, path: List[str]) -> List[str]:
    text = " / ".join(path + [title])
    topics: List[str] = []

    mapping = {
        "revenue": ["营业收入", "主营业务", "分产品", "分行业", "分地区", "收入确认"],
        "profit": ["净利润", "毛利率", "盈利能力", "每股收益", "净资产收益率"],
        "cashflow": ["现金流", "经营活动产生的现金流量净额"],
        "cash": ["货币资金"],
        "balance_sheet": ["资产", "负债", "资产构成", "资产及负债"],
        "receivables": ["应收账款", "应收票据", "应收款项融资", "其他应收款"],
        "prepayments": ["预付款项", "预付"],
        "inventory": ["存货"],
        "payables": ["应付账款", "应付票据", "其他应付款"],
        "contract": ["合同资产", "合同负债"],
        "risks": ["风险", "市场风险", "汇率风险", "信用风险", "流动性风险"],
        "growth_drivers": ["核心竞争力", "研发投入", "技术创新", "市场开拓", "海外", "订单", "产能"],
        "management_discussion": ["管理层讨论与分析", "经营情况", "未来发展", "经营计划"],
    }

    for topic, keywords in mapping.items():
        if any(k in text for k in keywords):
            topics.append(topic)

    return list(dict.fromkeys(topics))

def _filter_repeated_running_headings(
    candidates: List[Dict[str, Any]],
    *,
    max_keep_per_title: int = 2,
) -> List[Dict[str, Any]]:
    """
    过滤 PDF 每页重复出现的页眉型标题。

    年报里经常每页都有：
    第三节管理层讨论与分析
    第四节公司治理、环境和社会

    这些在第一次出现时有用，但每页重复出现会污染 section tree。
    """
    title_counts: Dict[str, int] = {}
    filtered: List[Dict[str, Any]] = []

    for c in candidates:
        title = str(c.get("text") or "").strip()
        level = int(c.get("rule_level") or 0)

        if not title:
            continue

        title_counts[title] = title_counts.get(title, 0) + 1

        # 只对一级章节页眉做限流
        if level == 1 and title_counts[title] > max_keep_per_title:
            continue

        filtered.append(c)

    return filtered


def _close_previous_section(sections: List[Dict[str, Any]], end_offset: int) -> None:
    if not sections:
        return

    last = sections[-1]
    if last.get("end") is None:
        last["end"] = max(end_offset, int(last.get("start", 0)))


def build_document_structure_from_report(
    *,
    report_md_path: Path,
    output_path: Optional[Path] = None,
    file_id: str = "",
    filename: str = "",
    use_llm_heading_judge: bool = False,
    llm_model_name: str = "qwen2.5:7b-instruct",
) -> Dict[str, Any]:
    if not report_md_path.exists():
        return {
            "ok": False,
            "error": f"report.md not found: {report_md_path}",
            "sections": [],
        }

    text = report_md_path.read_text(encoding="utf-8", errors="replace")
    raw_lines = text.splitlines(keepends=True)

    line_records: List[Dict[str, Any]] = []
    current_page: Optional[int] = None
    offset = 0

    # 1. 扫描所有行，生成候选 heading
    candidates: List[Dict[str, Any]] = []

    for i, raw_line in enumerate(raw_lines):
        line_text = raw_line.rstrip("\n")
        clean = _normalize_line(line_text)

        page_match = _PAGE_RE.match(clean)
        if page_match:
            current_page = int(page_match.group(1))

        is_heading, level, reason = _rule_detect_heading(clean)

        record = {
            "line_index": i,
            "text": clean,
            "page": current_page,
            "offset": offset,
            "rule_is_heading": is_heading,
            "rule_level": level,
            "rule_reason": reason,
        }

        line_records.append(record)

        if is_heading:
            prev_text = ""
            next_text = ""

            for j in range(i - 1, max(-1, i - 6), -1):
                p = _normalize_line(raw_lines[j])
                if p and not _PAGE_RE.match(p):
                    prev_text = p
                    break

            for j in range(i + 1, min(len(raw_lines), i + 6)):
                n = _normalize_line(raw_lines[j])
                if n and not _PAGE_RE.match(n):
                    next_text = n
                    break

            candidates.append(
                {
                    "line_index": i,
                    "text": clean,
                    "page": current_page,
                    "offset": offset,
                    "rule_level": level,
                    "rule_reason": reason,
                    "prev": prev_text,
                    "next": next_text,
                }
            )

        offset += len(raw_line)
    
    # 1.5 过滤重复页眉型标题
    candidates = _filter_repeated_running_headings(
        candidates,
        max_keep_per_title=1,
    )

    # 2. 可选：LLM 判断候选标题
    llm_judges: Dict[int, Dict[str, Any]] = {}

    if use_llm_heading_judge and candidates:
        llm_judges = _judge_candidates_with_llm(
            candidates=candidates,
            model_name=llm_model_name,
            batch_size=40,
            timeout=120,
        )

    candidate_by_line: Dict[int, Dict[str, Any]] = {}

    for idx, c in enumerate(candidates):
        judge = llm_judges.get(idx)

        if judge:
            is_heading = bool(judge.get("is_heading"))
            level = int(judge.get("level") or 0)
            reason = judge.get("reason", "")
            source = "llm"
        else:
            is_heading = True
            level = int(c.get("rule_level") or 0)
            reason = c.get("rule_reason", "")
            source = "rule"

        candidate_by_line[int(c["line_index"])] = {
            "is_heading": is_heading,
            "level": level,
            "judge_reason": reason,
            "judge_source": source,
        }

    # 3. 构建 section tree
    sections: List[Dict[str, Any]] = []
    section_stack: List[str] = []

    for rec in line_records:
        line_index = int(rec["line_index"])
        judge = candidate_by_line.get(line_index)

        if not judge or not judge.get("is_heading"):
            continue

        title = rec["text"]
        level = max(1, int(judge.get("level") or rec.get("rule_level") or 1))

        _close_previous_section(sections, int(rec["offset"]))

        section_stack = section_stack[: max(level - 1, 0)]
        section_stack.append(title)

        section_path = list(section_stack)

        sections.append(
            {
                "section_id": f"s{len(sections) + 1:04d}",
                "section_title": title,
                "section_path": section_path,
                "level": level,
                "page": rec.get("page"),
                "start": rec.get("offset"),
                "end": None,
                "section_type": _classify_section_type(title, section_path),
                "financial_topic": _infer_financial_topics(title, section_path),
                "judge_source": judge.get("judge_source"),
                "judge_reason": judge.get("judge_reason"),
            }
        )

    _close_previous_section(sections, len(text))

    result = {
        "ok": True,
        "file_id": file_id,
        "filename": filename,
        "report_md": str(report_md_path),
        "section_count": len(sections),
        "candidate_count": len(candidates),
        "use_llm_heading_judge": use_llm_heading_judge,
        "llm_model_name": llm_model_name if use_llm_heading_judge else "",
        "sections": sections,
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return result