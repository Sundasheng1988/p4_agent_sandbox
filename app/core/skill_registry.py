# skill_registry.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional


SkillHandler = Callable[..., Awaitable[Dict[str, Any]]]


@dataclass
class SkillSpec:
    name: str
    description: str
    handler: SkillHandler


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: Dict[str, SkillSpec] = {}

    def register(self, spec: SkillSpec) -> None:
        self._skills[spec.name] = spec

    def get(self, name: str) -> Optional[SkillSpec]:
        return self._skills.get(name)

    def list_names(self) -> list[str]:
        return sorted(self._skills.keys())