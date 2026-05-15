# analyzer.py
from __future__ import annotations

from typing import Any, Dict, List

METRIC_ALIAS = {
    "revenue": ["营业收入（元）", "营业收入"],
    "net_profit": ["归属于上市公司股东的净利润（元）"],
    "deduct_profit": ["归属于上市公司股东的扣除非经常性损益的净利润（元）"],
    "cashflow": ["经营活动产生的现金流量净额（元）"],
    "roe": ["加权平均净资产收益率"],
    "gross_margin": ["毛利率"],
    "cash": ["货币资金"],
    "ar": ["应收账款"],
    "ap": ["应付账款"],
}

async def analyze_financial_metrics(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    summary = state.get("build_financial_summary", {}).get("financial_summary", {})
    metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}
    quarter_metrics = summary.get("quarter_metrics", {}) if isinstance(summary, dict) else {}

    def get_value(metric_name: str, col_name: str) -> float | None:
        item = metrics.get(metric_name)
        if not isinstance(item, dict):
            return None

        v = item.get(col_name)

        # 新结构：current / previous / yoy
        if isinstance(v, (int, float)):
            return float(v)

        # 旧结构：{"value": xxx, "raw": xxx}
        if isinstance(v, dict):
            value = v.get("value")
            if isinstance(value, (int, float)):
                return float(value)

        return None

    def find_value(names: List[str], cols: List[str]) -> float | None:
        """
        按 metric name 优先，再按字段名查找。
        避免不同指标之间串值。
        """
        for name in names:
            if name not in metrics:
                continue

            for col in cols:
                v = get_value(name, col)
                if isinstance(v, (int, float)):
                    return float(v)

        return None
    
    def q_value(metric_name: str, quarter: str) -> float | None:
        item = quarter_metrics.get(metric_name)
        if not isinstance(item, dict):
            return None

        v = item.get(quarter)
        if isinstance(v, dict):
            value = v.get("value")
            if isinstance(value, (int, float)):
                return float(value)

        if isinstance(v, (int, float)):
            return float(v)

        return None


    def calc_qoq(q4: float | None, q3: float | None) -> float | None:
        if q4 is None or q3 in (None, 0):
            return None
        return (q4 - q3) / q3 * 100

    # =========================
    # 1. 核心指标取值
    # =========================
    revenue = find_value(
        ["营业收入（元）", "营业收入"],
        ["current", "本报告期", "value_1"],
    )

    revenue_yoy = find_value(
        ["营业收入（元）", "营业收入"],
        ["yoy", "本报告期比上年同期增减（%）", "value_3"],
    )

    net_profit = find_value(
        ["归属于上市公司股东的净利润（元）", "归属于上市公司股东的净利润"],
        ["current", "本报告期", "value_1"],
    )

    net_profit_yoy = find_value(
        ["归属于上市公司股东的净利润（元）", "归属于上市公司股东的净利润"],
        ["yoy", "本报告期比上年同期增减（%）", "value_3"],
    )

    deduct_profit = find_value(
        [
            "归属于上市公司股东的扣除非经常性损益的净利润（元）",
            "归属于上市公司股东的扣除非经常性损益的净利润",
        ],
        ["current", "本报告期", "value_1"],
    )

    deduct_profit_yoy = find_value(
        [
            "归属于上市公司股东的扣除非经常性损益的净利润（元）",
            "归属于上市公司股东的扣除非经常性损益的净利润",
        ],
        ["yoy", "本报告期比上年同期增减（%）", "value_3"],
    )

    operating_cashflow = find_value(
        ["经营活动产生的现金流量净额（元）", "经营活动产生的现金流量净额"],
        ["current", "本报告期", "value_1"],
    )

    roe = find_value(
        ["加权平均净资产收益率", "加权平均净资产收益率（%）"],
        ["current", "本报告期", "value_1"],
    )

    total_assets = find_value(
        ["总资产（元）", "总资产"],
        ["current", "本报告期末", "value_1"],
    )

    equity = find_value(
        ["归属于上市公司股东的所有者权益（元）", "归属于上市公司股东的所有者权益"],
        ["current", "本报告期末", "value_1"],
    )

    # =========================
    # 2. 分析结果结构
    # =========================
    analysis: Dict[str, Any] = {
        "growth": {},
        "profitability": {},
        "cashflow": {},
        "balance_sheet": {},
        "signals": [],
        "warnings": [],
        "quarter": {},
    }

    # =========================
    # 3. 增长分析
    # =========================
    if revenue_yoy is not None:
        analysis["growth"]["营业收入同比"] = f"{revenue_yoy:.2f}%"

        if revenue_yoy >= 30:
            analysis["signals"].append("营业收入高速增长。")
        elif revenue_yoy >= 10:
            analysis["signals"].append("营业收入保持增长。")
        elif revenue_yoy >= 0:
            analysis["warnings"].append("营业收入增长偏弱。")
        else:
            analysis["warnings"].append("营业收入同比下降。")

    if net_profit_yoy is not None:
        analysis["growth"]["归母净利润同比"] = f"{net_profit_yoy:.2f}%"

        if net_profit_yoy >= 30:
            analysis["signals"].append("归母净利润增长较快。")
        elif net_profit_yoy >= 0:
            analysis["signals"].append("归母净利润保持增长。")
        else:
            analysis["warnings"].append("归母净利润同比下降。")

    if deduct_profit_yoy is not None:
        analysis["growth"]["扣非归母净利润同比"] = f"{deduct_profit_yoy:.2f}%"

        if net_profit_yoy is not None and deduct_profit_yoy >= net_profit_yoy:
            analysis["signals"].append("扣非利润表现不弱于归母净利润，主营盈利质量较好。")
        elif net_profit_yoy is not None:
            analysis["warnings"].append("扣非净利润增速低于归母净利润，需要关注非经常性损益影响。")

    # =========================
    # 4. 盈利能力
    # =========================
    if revenue is not None and revenue > 0 and net_profit is not None:
        net_margin = net_profit / revenue * 100
        analysis["profitability"]["净利率"] = f"{net_margin:.2f}%"

    if revenue is not None and revenue > 0 and deduct_profit is not None:
        deduct_margin = deduct_profit / revenue * 100
        analysis["profitability"]["扣非净利率"] = f"{deduct_margin:.2f}%"

    if roe is not None:
        analysis["profitability"]["ROE"] = f"{roe:.2f}%"
    
    gross_margin = find_value(
        ["毛利率"],
        ["current", "本报告期", "value_1"],
    )

    if gross_margin is not None:
        analysis["profitability"]["毛利率"] = f"{gross_margin:.2f}%"

    # =========================
    # 5. 现金流质量
    # =========================
    if operating_cashflow is not None:
        analysis["cashflow"]["经营现金流净额"] = operating_cashflow

        if operating_cashflow > 0:
            analysis["signals"].append("经营现金流为正。")
        else:
            analysis["warnings"].append("经营现金流为负，需要关注回款和营运资本占用。")

    if operating_cashflow is not None and net_profit not in (None, 0):
        cash_profit_ratio = operating_cashflow / net_profit
        analysis["cashflow"]["经营现金流/归母净利润"] = round(cash_profit_ratio, 2)

        if cash_profit_ratio >= 1:
            analysis["signals"].append("经营现金流覆盖净利润，现金流质量较好。")
        elif cash_profit_ratio >= 0:
            analysis["warnings"].append("经营现金流低于净利润，需关注利润含金量。")
        else:
            analysis["warnings"].append("经营现金流与净利润背离，需重点关注现金流质量。")

    # =========================
    # 6. 资产负债结构
    # =========================
    if total_assets is not None:
        analysis["balance_sheet"]["总资产"] = total_assets

    if equity is not None:
        analysis["balance_sheet"]["归母权益"] = equity

    if total_assets not in (None, 0) and equity is not None:
        equity_ratio = equity / total_assets * 100
        analysis["balance_sheet"]["归母权益/总资产"] = f"{equity_ratio:.2f}%"

    for metric_key, names in {
        "营业收入": ["营业收入（元）", "营业收入"],
        "归属于上市公司股东的净利润": ["归属于上市公司股东的净利润（元）", "归属于上市公司股东的净利润"],
        "归属于上市公司股东的扣除非经常性损益的净利润": [
            "归属于上市公司股东的扣除非经常性损益的净利润（元）",
            "归属于上市公司股东的扣除非经常性损益的净利润",
        ],
        "经营活动产生的现金流量净额": ["经营活动产生的现金流量净额（元）", "经营活动产生的现金流量净额"],
    }.items():

        q3 = None
        q4 = None

        for name in names:
            if q3 is None:
                q3 = q_value(name, "Q3")
            if q4 is None:
                q4 = q_value(name, "Q4")

        # 👉 fallback：去掉单位再查一次
        if q3 is None or q4 is None:
            for key in quarter_metrics.keys():
                if any(n.replace("（元）", "") in key for n in names):
                    if q3 is None:
                        q3 = q_value(key, "Q3")
                    if q4 is None:
                        q4 = q_value(key, "Q4")

        qoq = calc_qoq(q4, q3)

        if q4 is None:
            continue

        display_name = metric_key
        if "扣除非经常性损益" in metric_key:
            display_name += "（扣非）"

        analysis["quarter"][display_name] = {
            "第四季度": q4,
            "第三季度": q3,
            "环比": f"{qoq:.2f}%" if qoq is not None else "材料中未体现",
            "同比": "材料中未体现",
        }

    return {
        "ok": True,
        "financial_analysis": analysis,
    }