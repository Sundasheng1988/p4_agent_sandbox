# extractor.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from app.skills.financial.resolver import resolve_financial_pdf

def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return ""
    except Exception:
        return ""

def to_number(raw: str) -> Any:
     raw = str(raw).strip()
     cleaned = raw.replace(",", "").replace("%", "").strip()

     try:
          num = float(cleaned)
     except Exception:
          return {"raw": raw}

     if "%" in raw:
          return {"value": num, "unit": "%", "raw": raw}

     return {"value": num, "raw": raw}

async def collect_financial_inputs(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    v3：基于用户输入解析公司 + 年份 + 报告期，并匹配最合适 PDF
    """

    user_input = state.get("user_input", "")

    try:
        rows = await ctx.store.list_files(limit=200)
    except Exception:
        rows = []

    if not rows:
        return {
            "ok": False,
            "error": "no files in store",
        }

    # 👉 核心：调用 resolver
    result = resolve_financial_pdf(
        rows=rows,
        sandbox_root=sandbox_root,
        user_input=user_input,
    )

    # 👉 Debug 信息（非常关键）
    if result.get("ok"):
        return {
            "ok": True,
            "file_id": result["file_id"],
            "filename": result["filename"],
            "pdf_path": result["pdf_path"],
            "parse_dir": result["parse_dir"],
            "match_score": result.get("match_score"),
            "query": result.get("query"),
            "candidates": result.get("candidates", []),
        }

    return result


async def extract_financial_text(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    inputs = state.get("collect_financial_inputs", {})
    markdown_path = Path(inputs.get("parse_dir", "")) / "report.md"

    if not markdown_path.exists():
        return {
            "ok": False,
            "error": f"financial markdown not found: {markdown_path}",
        }

    text = _safe_read_text(markdown_path)

    return {
        "ok": True,
        "text_path": str(markdown_path),
        "text_length": len(text),
        "text_preview": text[:1000],
    }


async def extract_financial_tables(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    import json

    inputs = state.get("collect_financial_inputs", {})
    tables_dir = Path(inputs.get("parse_dir", "")) / "tables"

    if not tables_dir.exists():
        return {
            "ok": False,
            "error": f"financial tables dir not found: {tables_dir}",
        }

    tables = []

    for csv_path in sorted(tables_dir.glob("*.csv")):
        json_path = csv_path.with_suffix(".json")

        table_info = {
            "csv": str(csv_path),
            "json": str(json_path) if json_path.exists() else "",
            "filename": csv_path.name,
        }

        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                table_info["rows"] = len(data) if isinstance(data, list) else 0
            except Exception:
                table_info["rows"] = 0
        else:
            table_info["rows"] = 0

        tables.append(table_info)

    return {
        "ok": True,
        "table_count": len(tables),
        "tables": tables,
    }

async def extract_financial_evidence(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    财报原文证据抽取层 v1。

    目标：
    - 不做推理
    - 不做总结
    - 只从 report.md / tables/*.csv 中抽取与财务分析相关的原文证据
    - 保留 source / page / table / 原文片段 / chunk_id 信息

    输出：
    state["extract_financial_evidence"]["evidence"]
    """

    import csv
    import json
    import re

    inputs = state.get("collect_financial_inputs", {})
    file_id = inputs.get("file_id")
    filename = inputs.get("filename")
    parse_dir = Path(inputs.get("parse_dir", ""))

    report_md = parse_dir / "report.md"
    tables_dir = parse_dir / "tables"

    if not file_id:
        return {
            "ok": False,
            "error": "missing file_id",
        }

    if not report_md.exists():
        return {
            "ok": False,
            "error": f"report.md not found: {report_md}",
        }

    text = _safe_read_text(report_md)

    evidence: Dict[str, List[Dict[str, Any]]] = {
        "revenue": [],
        "profit": [],
        "cashflow": [],
        "balance_sheet": [],
        "segments": [],
        "receivables_payables": [],
        "prepayments": [],
        "risks": [],
        "management_discussion": [],
    }

    # =========================
    # 1. 工具函数
    # =========================
    def _guess_page_from_text(snippet: str) -> Any:
        m = re.search(r"# Page\s+(\d+)", snippet)
        if m:
            return int(m.group(1))

        m = re.search(r"第\s*(\d+)\s*页", snippet)
        if m:
            return int(m.group(1))

        return None

    def _make_text_evidence(
        *,
        category: str,
        topic: str,
        snippet: str,
        keyword: str,
    ) -> None:
        snippet = (snippet or "").strip()
        if not snippet:
            return

        evidence[category].append(
            {
                "evidence_type": "text",
                "topic": topic,
                "keyword": keyword,
                "source": str(report_md),
                "filename": filename,
                "file_id": file_id,
                "page": _guess_page_from_text(snippet),
                "chunk_id": None,
                "original_text": snippet,
            }
        )

    def _make_table_evidence(
        *,
        category: str,
        topic: str,
        csv_path: Path,
        row_index: int,
        headers: List[str],
        row: List[str],
        matched_keyword: str,
    ) -> None:
        page_no = None
        table_no = None

        m = re.search(r"page_(\d+)_table_(\d+)", csv_path.name)
        if m:
            page_no = int(m.group(1))
            table_no = int(m.group(2))

        row_text = " | ".join([str(x or "").strip() for x in row if str(x or "").strip()])

        row_data: Dict[str, Any] = {}
        for i, cell in enumerate(row):
            key = headers[i] if i < len(headers) and headers[i] else f"列{i}"
            row_data[str(key)] = str(cell or "").strip()

        evidence[category].append(
            {
                "evidence_type": "table",
                "topic": topic,
                "keyword": matched_keyword,
                "source": str(csv_path),
                "filename": filename,
                "file_id": file_id,
                "page": page_no,
                "table": table_no,
                "row_index": row_index,
                "chunk_id": f"{file_id}_table_{page_no}_{table_no}_{row_index}" if page_no and table_no else None,
                "headers": headers,
                "row": row,
                "row_data": row_data,
                "original_text": row_text,
            }
        )

    def _find_text_windows(
        *,
        keyword: str,
        window: int = 900,
        max_hits: int = 5,
    ) -> List[str]:
        out: List[str] = []

        for m in re.finditer(re.escape(keyword), text):
            start = max(0, m.start() - window // 2)
            end = min(len(text), m.end() + window // 2)
            snippet = text[start:end].strip()

            if snippet and snippet not in out:
                out.append(snippet)

            if len(out) >= max_hits:
                break

        return out

    def _row_contains_any(row: List[str], keywords: List[str]) -> str:
        row_text = " ".join([str(x or "") for x in row])
        for kw in keywords:
            if kw in row_text:
                return kw
        return ""

    # =========================
    # 2. 关键词配置
    # =========================
    keyword_groups: Dict[str, Dict[str, Any]] = {
        "revenue": {
            "topic": "收入表现",
            "keywords": [
                "营业收入",
                "主营业务收入",
                "分行业",
                "分产品",
                "分地区",
                "营业收入比上年同期增减",
                "同比增减",
            ],
        },
        "profit": {
            "topic": "利润与盈利能力",
            "keywords": [
                "归属于上市公司股东的净利润",
                "扣除非经常性损益",
                "毛利率",
                "净利率",
                "加权平均净资产收益率",
                "基本每股收益",
                "盈利能力",
            ],
        },
        "cashflow": {
            "topic": "现金流",
            "keywords": [
                "经营活动产生的现金流量净额",
                "经营活动现金流入小计",
                "经营活动现金流出小计",
                "现金流量",
                "现金流量项目",
            ],
        },
        "balance_sheet": {
            "topic": "资产负债结构",
            "keywords": [
                "资产构成重大变动情况",
                "货币资金",
                "存货",
                "合同资产",
                "合同负债",
                "短期借款",
                "长期借款",
                "总资产",
                "负债",
            ],
        },
        "receivables_payables": {
            "topic": "应收应付项目",
            "keywords": [
                "应收账款",
                "应收款项",
                "应收票据",
                "应付账款",
                "应付票据",
                "其他应收款",
                "其他应付款",
            ],
        },
        "prepayments": {
            "topic": "预付款项",
            "keywords": [
                "预付款项",
                "预付账款",
                "预收款项",
            ],
        },
        "segments": {
            "topic": "分业务/分产品/分地区",
            "keywords": [
                "分行业",
                "分产品",
                "分地区",
                "开关类业务",
                "变压器类业务",
                "储能系统及元件类业务",
                "电力电子类业务",
                "营业成本",
                "毛利率",
            ],
        },
        "risks": {
            "topic": "风险因素",
            "keywords": [
                "公司面临的风险及应对措施",
                "市场风险",
                "汇率风险",
                "税务风险",
                "应收账款风险",
                "合同风险",
                "工程分包风险",
                "外部采购风险",
            ],
        },
        "management_discussion": {
            "topic": "管理层讨论与分析",
            "keywords": [
                "第三节管理层讨论与分析",
                "报告期内公司从事的主要业务",
                "经营情况讨论与分析",
                "未来发展的展望",
                "核心竞争力",
                "研发投入",
                "全球化战略",
                "新兴赛道",
            ],
        },
    }

    # =========================
    # 3. 从 report.md 抽取正文证据
    # =========================
    for category, cfg in keyword_groups.items():
        topic = cfg["topic"]
        keywords = cfg["keywords"]

        seen_snippets = set()

        for kw in keywords:
            windows = _find_text_windows(
                keyword=kw,
                window=int(step.get("text_window", 900)),
                max_hits=int(step.get("max_text_hits_per_keyword", 3)),
            )

            for snippet in windows:
                compact = re.sub(r"\s+", "", snippet)
                if compact in seen_snippets:
                    continue

                seen_snippets.add(compact)

                _make_text_evidence(
                    category=category,
                    topic=topic,
                    snippet=snippet,
                    keyword=kw,
                )

    # =========================
    # 4. 从 tables/*.csv 抽取表格证据
    # =========================
    if tables_dir.exists():
        csv_files = sorted(tables_dir.glob("*.csv"))

        for csv_path in csv_files:
            try:
                with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                    reader = list(csv.reader(f))
            except Exception:
                continue

            if not reader:
                continue

            # 兼容表头不规则情况：
            # 默认取第一行做 headers；如果第一行为空，则继续往下找一行非空
            headers: List[str] = []
            header_row_index = 0

            for i, row in enumerate(reader[:5]):
                clean = [str(x or "").strip() for x in row]
                if any(clean):
                    headers = clean
                    header_row_index = i
                    break

            if not headers:
                continue

            for row_index, row in enumerate(reader[header_row_index + 1 :], start=header_row_index + 1):
                row = [str(x or "").strip() for x in row]
                if not any(row):
                    continue

                for category, cfg in keyword_groups.items():
                    topic = cfg["topic"]
                    keywords = cfg["keywords"]
                    matched_kw = _row_contains_any(row, keywords)

                    if not matched_kw:
                        continue

                    _make_table_evidence(
                        category=category,
                        topic=topic,
                        csv_path=csv_path,
                        row_index=row_index,
                        headers=headers,
                        row=row,
                        matched_keyword=matched_kw,
                    )

    # =========================
    # 5. 去重与限制数量
    # =========================
    max_items_per_category = int(step.get("max_items_per_category", 80))

    deduped: Dict[str, List[Dict[str, Any]]] = {}

    for category, items in evidence.items():
        seen = set()
        out = []

        for item in items:
            key = (
                item.get("evidence_type"),
                item.get("source"),
                item.get("page"),
                item.get("table"),
                item.get("row_index"),
                re.sub(r"\s+", "", str(item.get("original_text") or ""))[:200],
            )

            if key in seen:
                continue

            seen.add(key)
            out.append(item)

            if len(out) >= max_items_per_category:
                break

        deduped[category] = out

    stats = {
        category: len(items)
        for category, items in deduped.items()
    }

    return {
        "ok": True,
        "file_id": file_id,
        "filename": filename,
        "report_md": str(report_md),
        "tables_dir": str(tables_dir),
        "evidence": deduped,
        "stats": stats,
    }

def _extract_financial_metrics_from_text(text: str) -> Dict[str, Any]:
    import re

    metrics: Dict[str, Any] = {}

    patterns = {
     "营业收入": r"营业收入[\s\S]{0,80}?([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)[\s\n]+([\d,.]+)",
     "归属于上市公司股东的净利润": r"归属于上市公司股东的净利润[\s\S]{0,80}?([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)[\s\n]+([\d,.]+)",
     "归属于上市公司股东的扣除非经常性损益的净利润": r"归属于上市公司股东的扣除非经常[\s\S]{0,20}?性损益的净利润[\s\S]{0,80}?([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)[\s\n]+([\d,.]+)",
     "经营活动产生的现金流量净额": r"经营活动产生的现金流量净额[\s\S]{0,80}?([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)[\s\n]+([\d,.]+)",
     "基本每股收益（元/股）": r"基本每股收益[\s\S]{0,30}?([\d,.-]+)[\s\n]+([\d,.-]+)[\s\n]+([\d,.]+)",
     "稀释每股收益（元/股）": r"稀释每股收益[\s\S]{0,30}?([\d,.-]+)[\s\n]+([\d,.-]+)[\s\n]+([\d,.]+)",
     "研发投入合计": r"研发投入合计[\s\S]{0,80}?([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)[\s\n]+([\d,.]+)",
     "总资产": r"总资产[\s\S]{0,80}?([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)[\s\n]+([\d,.]+)",
     "归属于上市公司股东的所有者权益": r"归属于上市公司股东的所有者权益[\s\S]{0,80}?([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)[\s\n]+([\d,.]+)",
     "毛利率": r"毛利率[\s\S]{0,50}?([\d.]+)%",
     "货币资金": r"货币资金[\s\S]{0,80}?([\d,]+\.\d+)",
     "应收账款": r"应收账款[\s\S]{0,80}?([\d,]+\.\d+)",
     "应付账款": r"应付账款[\s\S]{0,80}?([\d,]+\.\d+)",
     }

    for name, pattern in patterns.items():
        m = re.search(pattern, text, re.S)
        if not m:
            continue

        # ✅ 单值指标：只有 current
        if name in ["毛利率", "货币资金", "应收账款", "应付账款"]:
            try:
                raw_value = m.group(1)

                if name == "毛利率":
                    metrics[name] = {
                        "current": float(raw_value.replace(",", "")),
                    }
                else:
                    metrics[name] = {
                        "current": float(raw_value.replace(",", "")),
                    }
            except Exception:
                metrics[name] = {}
            continue

        # ✅ 三列指标：current / previous / yoy
        try:
            metrics[name] = {
                "current": float(m.group(1).replace(",", "")),
                "previous": float(m.group(2).replace(",", "")),
                "yoy": float(m.group(3).replace(",", "").replace("%", "")),
            }
        except Exception:
            continue

    # 特殊：ROE 是“增加 1.39 个百分点”
    roe = re.search(r"加权平均净资产收益率（%）\s+([\d.]+)\s+([\d.]+)\s+增加\s+([\d.]+)\s+个百分点", text)
    if roe:
        metrics["加权平均净资产收益率（%）"] = {
            "本报告期": to_number(roe.group(1) + "%"),
            "上年同期": to_number(roe.group(2) + "%"),
            "变动": {"raw": f"增加 {roe.group(3)} 个百分点"},
        }

    return metrics

def _extract_quarter_metrics_from_text(text: str) -> Dict[str, Any]:
    import re

    quarter_metrics: Dict[str, Any] = {}

    section_match = re.search(
        r"分季度主要财务指标([\s\S]{0,3000}?)(?:非经常性损益|境内外会计准则|股本及股东情况)",
        text,
        re.S,
    )

    if not section_match:
        return quarter_metrics

    section = section_match.group(1)

    patterns = {
        "营业收入": r"营业收入[\s\S]{0,120}?([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)[\s\n]+([\d,]+\.\d+)",
        "归属于上市公司股东的净利润": r"归属于上市公司股东的净利润[\s\S]{0,120}?([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)",
        "归属于上市公司股东的扣除非经常性损益的净利润": r"归属于上市公司股东的扣除非经常[\s\S]{0,30}?性损益的净利润[\s\S]{0,120}?([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)",
        "经营活动产生的现金流量净额": r"经营活动产生的现金流量净额[\s\S]{0,120}?([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)[\s\n]+([\d,.-]+\.\d+)",
    }

    for name, pattern in patterns.items():
        m = re.search(pattern, section, re.S)
        if not m:
            continue

        quarter_metrics[name] = {
            "Q1": to_number(m.group(1)),
            "Q2": to_number(m.group(2)),
            "Q3": to_number(m.group(3)),
            "Q4": to_number(m.group(4)),
        }

    return quarter_metrics

async def build_financial_summary(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    import csv
    import re

    inputs = state.get("collect_financial_inputs", {})
    tables_dir = Path(inputs.get("parse_dir", "")) / "tables"

    if not tables_dir.exists():
        return {
            "ok": False,
            "error": f"financial tables dir not found: {tables_dir}",
        }

    def table_score(csv_path: Path) -> int:
        text = _safe_read_text(csv_path)
        score = 0

        keywords = [
            "营业收入",
            "归属于上市公司股东的净利润",
            "扣除非经常性损益",
            "经营活动产生的现金流量净额",
            "基本每股收益",
            "加权平均净资产收益率",
            "总资产",
            "归属于上市公司股东的所有者权益",
        ]

        for k in keywords:
            if k in text:
                score += 10

        # 年报主财务指标表通常在前几十页，不在财报附注后面
        m = re.search(r"page_(\d+)_table_", csv_path.name)
        if m:
            page_no = int(m.group(1))
            if page_no <= 30:
                score += 20
            elif page_no >= 80:
                score -= 20

        return score

    csv_files = sorted(tables_dir.glob("*.csv"))
    scored = [(table_score(p), p) for p in csv_files]
    scored = sorted(scored, key=lambda x: x[0], reverse=True)

    if not scored or scored[0][0] <= 0:
        return {
            "ok": False,
            "error": f"main financial table not found in: {tables_dir}",
        }

    target_table = scored[0][1]

    summary: Dict[str, Any] = {
        "company": "材料中未体现",
        "period": "材料中未体现",
        "source_table": str(target_table),
        "source_table_score": scored[0][0],
        "metrics": {},
    }

    current_columns: List[str] = []

    with target_table.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)

        for row in reader:
            row = [str(x or "").strip() for x in row]
            if not any(row):
                continue

            # 表头行
            if row[0] == "":
                current_columns = row[1:]
                continue

            metric_name = row[0].replace("\n", "").strip()
            values = row[1:]

            if not metric_name:
                continue

            metric_data: Dict[str, Any] = {}

            year_values = []
            yoy_value = None

            for i, v in enumerate(values):
                parsed = to_number(v)

                if parsed is None:
                    continue

                # 提取数值
                if isinstance(parsed, dict) and "value" in parsed:
                    val = parsed["value"]
                else:
                    continue

                # 判断是否是同比（而不是所有百分比）
                if isinstance(parsed, dict) and parsed.get("unit") == "%":
                    col_name = current_columns[i] if i < len(current_columns) else ""

                    if "增减" in col_name or "同比" in col_name:
                        yoy_value = val
                    else:
                        year_values.append(val)
                else:
                    year_values.append(val)

            # 构建统一结构
            if len(year_values) >= 1:
                metric_data["current"] = year_values[0]

            if len(year_values) >= 2:
                metric_data["previous"] = year_values[1]

            if yoy_value is not None:
                metric_data["yoy"] = yoy_value

            if len(year_values) > 2:
                metric_data["history"] = year_values[2:]

            summary["metrics"][metric_name] = metric_data

    # Fallback：从 report.md 正文补充缺失指标
    report_md = Path(inputs.get("parse_dir", "")) / "report.md"
    if report_md.exists():
        text = _safe_read_text(report_md)
        text_metrics = _extract_financial_metrics_from_text(text)

        quarter_metrics = _extract_quarter_metrics_from_text(text)
        summary["quarter_metrics"] = quarter_metrics

        for k, v in text_metrics.items():
            if k not in summary["metrics"] or not summary["metrics"].get(k):
                summary["metrics"][k] = v

        company_match = re.search(r"([\u4e00-\u9fa5（）()]+股份有限公司)", text)
        if company_match:
            summary["company"] = company_match.group(1)

        if "2026 年第一季度报告" in text:
            summary["period"] = "2026Q1"
        elif "2025 年年度报告" in text:
            summary["period"] = "2025A"

    return {
        "ok": True,
        "financial_summary": summary,
    }
