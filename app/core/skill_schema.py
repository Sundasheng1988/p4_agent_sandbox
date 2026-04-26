# skill_schema.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SkillStep:
    step_name: str
    action: str
    prompt: Optional[str] = None
    template_name: Optional[str] = None
    uses: List[str] = field(default_factory=list)
    output_key: Optional[str] = None


@dataclass
class SkillOutputSpec:
    artifact_type: str = "markdown"
    artifact_name: str = "output"


@dataclass
class SkillDefinition:
    skill_name: str
    description: str
    task_type: str = "workflow"
    input_requirements: List[str] = field(default_factory=list)
    steps: List[SkillStep] = field(default_factory=list)
    outputs: SkillOutputSpec = field(default_factory=SkillOutputSpec)
    success_criteria: List[str] = field(default_factory=list)


@dataclass
class SkillStepResult:
    step_name: str
    action: str
    ok: bool
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class SkillExecutionResult:
    ok: bool
    skill_name: str
    steps: List[SkillStepResult] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    artifact: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
