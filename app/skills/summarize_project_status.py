from __future__ import annotations

from typing import Any, Dict


def summarize_project_status(user_input: str) -> Dict[str, Any]:
    return {
        "skill_name": "summarize_project_status",
        "workflow_name": "summarize_project_status_workflow",
        "success_criteria": [
            "完成项目事实抽取",
            "完成基于事实的报告改写",
            "输出 markdown 文件",
        ],
        "steps": [
            {
                "key": "collect_inputs",
                "type": "collect_materials",
                "max_chars_per_file": 6000,
            },
            {
                "key": "extract_facts",
                "type": "extract_project_facts",
            },
            {
                "key": "rewrite_summary",
                "type": "rewrite_summary_from_facts",
            },
            {
                "key": "generate_report",
                "type": "generate_markdown_from_facts",
            },
        ],
    }