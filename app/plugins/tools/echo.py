from __future__ import annotations
from app.tools.spec import ToolSpec

def echo(text: str) -> str:
    return text

TOOL = ToolSpec(
    name="echo",
    handler=echo,
    risk="low",
    description="Return the input text.",
    args_schema={"text": "string"},
)