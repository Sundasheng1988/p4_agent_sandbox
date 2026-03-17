from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Literal

Risk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    handler: Callable[..., Any]
    risk: Risk = "low"
    description: str = ""
    args_schema: Dict[str, Any] = field(default_factory=dict)
