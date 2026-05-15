# app/skills/analyze_financial_report.py
from __future__ import annotations

from typing import Any, Dict


def analyze_financial_report(user_input: str) -> Dict[str, Any]:
    return {
        "skill_name": "analyze_financial_report",
        "workflow_name": "analyze_financial_report_workflow",
        "success_criteria": [
            "读取财报 PDF",
            "解析 PDF 为 Markdown 和表格",
            "抽取核心财务指标",
            "计算关键财务分析指标",
            "抽取关键表格变动说明",
            "生成 Markdown 财务分析报告",
        ],
        "steps": [
            {"key": "collect_financial_inputs", "type": "collect_financial_inputs"},
            {"key": "parse_financial_pdf", "type": "parse_financial_pdf"},
            {"key": "extract_financial_text", "type": "extract_financial_text"},
            {"key": "extract_financial_tables", "type": "extract_financial_tables"},
            {
                "key": "extract_financial_evidence",
                "type": "extract_financial_evidence",
                "text_window": 300,
                "max_text_hits_per_keyword": 2,
                "max_items_per_category": 80,
            },
            {"key": "build_financial_summary", "type": "build_financial_summary"},
            {"key": "analyze_financial_metrics", "type": "analyze_financial_metrics"},

            {
                "key": "extract_financial_reasons",
                "type": "extract_financial_reasons",
            },
            {
                "key": "verify_financial_reasons",
                "type": "verify_financial_reasons",
            },

            {
                "key": "financial_rag_analysis",
                "type": "analyze_financial_with_rag",
                "top_k": 8,
                "skip_llm": True,
                "model_name": "deepseek-r1:7b",
                "max_context_chars": 1500,
                "llm_sections": [
                    "company_profile",
                    "growth_drivers",
                    "risks",
                ],
            },

            {"key": "generate_report", "type": "generate_financial_report"},
        ],
    }