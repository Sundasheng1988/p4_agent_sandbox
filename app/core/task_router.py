# task_router.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class TaskRoutingResult:
    task_type: str              # "qa" | "skill"
    skill_name: Optional[str]
    reason: str


def route_task(user_input: str) -> TaskRoutingResult:
    q = (user_input or "").strip().lower()

    devlog_keywords = [
        "dev log",
        "开发日志",
        "生成开发日志",
        "新版dev log",
        "新版 dev log",
    ]

    project_status_keywords = [
        "总结项目状态",
        "项目总结",
        "阶段总结",
        "风险清单",
        "里程碑总结",
        "整理项目进展",
        "阶段汇报",
        "输出总结",
    ]

    financial_report_keywords = [
        "财报",
        "财务报告",
        "财务分析",
        "分析财报",
        "季度报告",
        "一季度报告",
        "半年报",
        "年报",
        "利润表",
        "资产负债表",
        "现金流量表",
        "financial report",
        "financial analysis",
    ]

    if any(k in q for k in financial_report_keywords):
        return TaskRoutingResult(
            task_type="skill",
            skill_name="analyze_financial_report",
            reason="matched_financial_report_keywords",
        )

    if any(k in q for k in devlog_keywords):
        return TaskRoutingResult(
            task_type="skill",
            skill_name="generate_dev_log",
            reason="matched_dev_log_keywords",
        )

    if any(k in q for k in project_status_keywords):
        return TaskRoutingResult(
            task_type="skill",
            skill_name="summarize_project_status",
            reason="matched_project_status_keywords",
        )

    return TaskRoutingResult(
        task_type="qa",
        skill_name=None,
        reason="default_to_qa",
    )