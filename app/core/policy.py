from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List
import os

SANDBOX_ROOT = os.path.expanduser("~/p4_agent_sandbox")


@dataclass
class PolicyDecision:
    allowed: bool
    risk: str
    reason: str


class Policy:
    """
    Epic A policy:
    - deny-by-default
    - allowlist tools
    - basic argument validation
    - file operations restricted under SANDBOX_ROOT
    - high-risk tools disabled
    """

    def __init__(self, allow_tools: List[str]):
        self.allow_tools = set(allow_tools)

    def check_tool(self, tool_name: str, args: Dict[str, Any]) -> PolicyDecision:
        # 1) deny by default
        if tool_name not in self.allow_tools:
            return PolicyDecision(False, "high", f"tool '{tool_name}' not in allowlist")

        # 2) high-risk tools disabled in Epic A
        if tool_name in {"shell_exec", "ros_exec", "hardware_control"}:
            return PolicyDecision(False, "high", "high-risk tool disabled in Epic A")

        # 3) file tools: path restrictions
        if tool_name in {"file_list", "file_read", "file_write"}:
            raw = str(args.get("path", ""))
            p = os.path.expanduser(raw)

            # simple traversal block (Epic A)
            if ".." in p:
                return PolicyDecision(False, "high", "path traversal detected ('..')")

            # must be under sandbox root
            if not p.startswith(SANDBOX_ROOT):
                return PolicyDecision(False, "high", f"path must be under sandbox: {SANDBOX_ROOT}")

        # 4) risk grading (coarse)
        risk = "low"
        if tool_name == "file_write":
            risk = "medium"

        return PolicyDecision(True, risk, "ok")


