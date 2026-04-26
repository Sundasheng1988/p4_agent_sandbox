# skill_loader.py

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from app.core.skill_schema import (
    SkillDefinition,
    SkillOutputSpec,
    SkillStep,
)


def _ensure_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def load_skill_from_yaml(path: str | Path) -> SkillDefinition:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    steps: List[SkillStep] = []
    for row in raw.get("steps", []) or []:
        steps.append(
            SkillStep(
                step_name=str(row.get("step_name", "")).strip(),
                action=str(row.get("action", "")).strip(),
                prompt=row.get("prompt"),
                template_name=row.get("template_name"),
                uses=_ensure_list(row.get("uses")),
                output_key=row.get("output_key"),
            )
        )

    outputs_raw: Dict[str, Any] = raw.get("outputs", {}) or {}
    outputs = SkillOutputSpec(
        artifact_type=str(outputs_raw.get("artifact_type", "markdown")).strip(),
        artifact_name=str(outputs_raw.get("artifact_name", "output")).strip(),
    )

    return SkillDefinition(
        skill_name=str(raw.get("skill_name", "")).strip(),
        description=str(raw.get("description", "")).strip(),
        task_type=str(raw.get("task_type", "workflow")).strip(),
        input_requirements=_ensure_list(raw.get("input_requirements")),
        steps=steps,
        outputs=outputs,
        success_criteria=_ensure_list(raw.get("success_criteria")),
    )