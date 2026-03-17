from __future__ import annotations
from app.tools.spec import ToolSpec
from app.builtins.file_ops import file_read

TOOL = ToolSpec(
    name="file_read",
    handler=file_read,
    risk="low",
    description="Read a text file under a sandbox path.",
    args_schema={"path": {"type": "string"}},
)
