#__init__.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

from app.skills.summarize_project_status import summarize_project_status
from app.skills.analyze_financial_report import analyze_financial_report


@dataclass
class SkillSpec:
    name: str
    builder: Callable[[str], Dict[str, Any]]
    description: str = ""


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: Dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        self._skills[spec.name] = spec

    def get(self, name: str) -> SkillSpec | None:
        return self._skills.get(name)

    def list_names(self) -> list[str]:
        return list(self._skills.keys())


def load_skills() -> SkillRegistry:
    reg = SkillRegistry()

    reg.register(
        SkillSpec(
            name="summarize_project_status",
            builder=summarize_project_status,
            description="根据项目材料生成阶段总结与风险清单",
        )
    )

    reg.register(
        SkillSpec(
            name="analyze_financial_report",
            builder=analyze_financial_report,
            description="根据财报文本与表格生成财务分析报告",
        )
    )

    return reg