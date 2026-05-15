# app/skills/financial/reporter.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime
from zoneinfo import ZoneInfo


def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _num(value: Any) -> float | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, dict):
        v = value.get("value")
        if isinstance(v, (int, float)):
            return float(v)

    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def _fmt_money(value: Any) -> str:
    n = _num(value)
    if n is None:
        return "材料中未体现"
    return f"{n:,.2f} 元"


def _fmt_percent(value: Any) -> str:
    n = _num(value)
    if n is None:
        return "材料中未体现"
    return f"{n:.2f}%"


def _fmt_value(value: Any) -> str:
    if value is None:
        return "材料中未体现"

    if isinstance(value, dict):
        if "raw" in value and "value" not in value:
            return str(value.get("raw"))
        if "value" in value:
            return str(value.get("value"))

    return str(value)


async def generate_financial_report(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    filename = f"financial_report_{now.strftime('%Y%m%d_%H%M%S')}.md"

    user_input = str(state.get("user_input", "")).strip()

    summary = state.get("build_financial_summary", {}).get("financial_summary", {})
    if not isinstance(summary, dict):
        summary = {}

    metrics = summary.get("metrics", {})
    if not isinstance(metrics, dict):
        metrics = {}

    analysis = state.get("analyze_financial_metrics", {}).get("financial_analysis", {})
    if not isinstance(analysis, dict):
        analysis = {}

    verified_reasons = state.get("verify_financial_reasons", {}).get("reasons", {})
    if not isinstance(verified_reasons, dict):
        verified_reasons = {}

    rag_block = state.get("financial_rag_analysis", {})
    rag_analysis = rag_block.get("analysis", {}) if isinstance(rag_block, dict) else {}
    has_valid_answer = bool(rag_block.get("has_valid_answer", False)) if isinstance(rag_block, dict) else False

    def get_metric(*names: str) -> Dict[str, Any]:
        for name in names:
            item = metrics.get(name)
            if isinstance(item, dict):
                return item
        return {}

    def render_metric_row(title: str, item: Dict[str, Any], unit: str = "money") -> str:
        if not item:
            return f"| {title} | 材料中未体现 | 材料中未体现 | 材料中未体现 |"

        current = item.get("current")
        previous = item.get("previous")
        yoy = item.get("yoy")

        if unit == "percent":
            current_text = _fmt_percent(current)
            previous_text = _fmt_percent(previous)
        elif unit == "raw":
            current_text = _fmt_value(current)
            previous_text = _fmt_value(previous)
        else:
            current_text = _fmt_money(current)
            previous_text = _fmt_money(previous)

        yoy_text = _fmt_percent(yoy)

        return f"| {title} | {current_text} | {previous_text} | {yoy_text} |"

    def render_core_metrics() -> str:
        rows = [
            render_metric_row(
                "营业收入",
                get_metric("营业收入（元）", "营业收入"),
            ),
            render_metric_row(
                "归母净利润",
                get_metric("归属于上市公司股东的净利润（元）", "归属于上市公司股东的净利润"),
            ),
            render_metric_row(
                "扣非归母净利润",
                get_metric(
                    "归属于上市公司股东的扣除非经常性损益的净利润（元）",
                    "归属于上市公司股东的扣除非经常性损益的净利润",
                ),
            ),
            render_metric_row(
                "经营活动现金流量净额",
                get_metric("经营活动产生的现金流量净额（元）", "经营活动产生的现金流量净额"),
            ),
            render_metric_row(
                "总资产",
                get_metric("总资产（元）", "总资产"),
            ),
            render_metric_row(
                "归母权益",
                get_metric(
                    "归属于上市公司股东的所有者权益（元）",
                    "归属于上市公司股东的所有者权益",
                ),
            ),
        ]

        return "\n".join(
            [
                "| 指标 | 本期 | 上期 | 同比/变动 |",
                "|---|---:|---:|---:|",
                *rows,
            ]
        )

    def render_dict_block(data: Dict[str, Any]) -> str:
        if not data:
            return "- 材料中未体现。"
        return "\n".join([f"- {k}：{v}" for k, v in data.items()])

    def render_list_block(items: List[Any]) -> str:
        if not items:
            return "- 材料中未体现。"
        return "\n".join([f"- {str(x)}" for x in items])

    def render_quarter_block() -> str:
        quarter = analysis.get("quarter", {})
        if not isinstance(quarter, dict) or not quarter:
            return "- 材料中未体现。"

        lines: List[str] = []

        for name, item in quarter.items():
            if not isinstance(item, dict):
                continue

            lines.append(f"### {name}")
            lines.append(f"- 第四季度：{_fmt_money(item.get('第四季度'))}")
            lines.append(f"- 第三季度：{_fmt_money(item.get('第三季度'))}")
            lines.append(f"- 环比：{item.get('环比', '材料中未体现')}")
            lines.append("")

        return "\n".join(lines).strip() or "- 材料中未体现。"

    def get_rag_answer(key: str) -> str:
        item = rag_analysis.get(key, {})
        if not isinstance(item, dict):
            return "材料中未体现。"

        error = item.get("error")
        answer = str(item.get("answer") or "").strip()

        if error:
            return f"检索或生成失败：{error}"

        if not answer:
            return "材料中未体现。"

        if "未在知识库中找到明确答案" in answer:
            return "材料中未体现。"

        return answer
    
    def render_verified_reasons() -> str:
        if not verified_reasons:
            return "- 材料中未体现。"

        lines = []
        for metric_name, item in verified_reasons.items():
            if not isinstance(item, dict):
                continue

            reason = str(item.get("reason") or "").strip()
            source = str(item.get("source") or "").strip()
            chunk_id = str(item.get("chunk_id") or "").strip()

            if not reason:
                continue

            src = f"（来源：{source} / {chunk_id}）" if source or chunk_id else ""
            lines.append(f"- {metric_name}：{reason}{src}")

        return "\n".join(lines) if lines else "- 材料中未体现。"

    def render_sources() -> str:
        lines: List[str] = []
        seen = set()

        for _, item in rag_analysis.items():
            if not isinstance(item, dict):
                continue

            hits = item.get("hits", []) or []
            for h in hits[:3]:
                filename_h = h.get("filename")
                chunk_id = h.get("chunk_id")
                score = h.get("score")

                if not filename_h or not chunk_id:
                    continue

                uniq = (filename_h, chunk_id)
                if uniq in seen:
                    continue

                seen.add(uniq)
                lines.append(f"- {filename_h} / {chunk_id} / score={score}")

        if not lines:
            return "- 材料中未体现。"

        return "\n".join(lines)

    company = summary.get("company", "材料中未体现")
    period = summary.get("period", "材料中未体现")
    source_table = summary.get("source_table", "材料中未体现")

    growth = analysis.get("growth", {})
    profitability = analysis.get("profitability", {})
    cashflow = analysis.get("cashflow", {})
    balance_sheet = analysis.get("balance_sheet", {})
    signals = analysis.get("signals", [])
    warnings = analysis.get("warnings", [])

    reliability_note = (
        "RAG 已检索到部分有效财报内容，业务解释与风险分析来自知识库检索结果。"
        if has_valid_answer
        else "RAG 未稳定检索到足够明确的解释性内容，数值指标主要来自结构化抽取结果。"
    )

    markdown = f"""# 财务分析报告

生成时间：{generated_at}

## 一、用户任务

{user_input}

## 二、报告对象

- 公司：{company}
- 报告期：{period}
- 核心指标来源表：{source_table}

## 三、核心财务指标

{render_core_metrics()}

## 四、结构化财务分析

### 1. 增长情况

{render_dict_block(growth)}

### 2. 盈利能力

{render_dict_block(profitability)}

### 3. 现金流质量

{render_dict_block(cashflow)}

### 4. 资产负债结构

{render_dict_block(balance_sheet)}

### 5. 积极信号

{render_list_block(signals)}

### 6. 风险与关注点

{render_list_block(warnings)}

## 五、关键指标变动原因

{render_verified_reasons()}

## 六、季度表现

{render_quarter_block()}

## 七、主营业务与业务结构

{get_rag_answer("company_profile")}

## 八、收入表现解释

{get_rag_answer("revenue")}

## 九、利润与盈利能力解释

{get_rag_answer("profit")}

## 十、现金流解释

{get_rag_answer("cashflow")}

## 十一、资产负债与财务风险解释

{get_rag_answer("balance_sheet")}

## 十二、分业务 / 分产品 / 分地区表现

{get_rag_answer("segments")}

## 十三、增长驱动因素

{get_rag_answer("growth_drivers")}

## 十四、主要风险因素

{get_rag_answer("risks")}

## 十五、管理层讨论与未来展望

{get_rag_answer("management_discussion")}

## 十六、引用来源

{render_sources()}

## 十七、说明

- {reliability_note}
- 数值类指标优先来自结构化表格/正文抽取，解释类内容来自 RAG 检索。
- 本报告仅基于已上传并进入知识库的材料生成，不构成投资建议。
""".strip() + "\n"

    output_path = Path(sandbox_root) / "artifacts" / "deliverables" / filename
    _ensure_dir(output_path)
    output_path.write_text(markdown, encoding="utf-8")

    return {
        "ok": True,
        "artifact": {
            "type": "markdown",
            "path": str(output_path),
            "filename": output_path.name,
            "created_at": generated_at,
        },
        "content": markdown,
    }