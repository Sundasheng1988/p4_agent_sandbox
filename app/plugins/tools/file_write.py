from __future__ import annotations
from app.tools.spec import ToolSpec
from app.builtins.file_ops import file_write

TOOL = ToolSpec(
    name="file_write",
    handler=file_write,
    risk="medium",
    description="Write text to a file under a sandbox path.",
    args_schema={"path": {"type": "string"}, "content": {"type": "string"}},
)
