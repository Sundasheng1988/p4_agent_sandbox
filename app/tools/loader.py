from __future__ import annotations

import importlib
import pkgutil
from typing import Any, Dict

from app.tools.spec import ToolSpec
from app.tools.base import ToolRegistry


def load_tool_plugins(registry: ToolRegistry, package: str = "app.plugins.tools") -> Dict[str, Any]:
    """
    Scan `package` and auto-register tools.
    Plugin module must export either:
      - TOOL: ToolSpec
      - or TOOLS: list[ToolSpec]

    A2.3 behavior:
      - do not crash on a single plugin import failure
      - return a report dict: {loaded: [...], failed: [...]}
    """
    report = {"loaded": [], "failed": []}

    pkg = importlib.import_module(package)

    for m in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        mod_name = m.name
        try:
            mod = importlib.import_module(mod_name)

            # single tool
            if hasattr(mod, "TOOL"):
                tool = getattr(mod, "TOOL")
                if not isinstance(tool, ToolSpec):
                    raise TypeError(f"{mod_name}.TOOL is not ToolSpec")
                registry.register_spec(tool)
                report["loaded"].append(tool.name)

            # multiple tools
            if hasattr(mod, "TOOLS"):
                tools = getattr(mod, "TOOLS")
                if not isinstance(tools, list):
                    raise TypeError(f"{mod_name}.TOOLS is not list[ToolSpec]")
                for t in tools:
                    if not isinstance(t, ToolSpec):
                        raise TypeError(f"{mod_name}.TOOLS contains non-ToolSpec item")
                    registry.register_spec(t)
                    report["loaded"].append(t.name)

        except Exception as e:
            report["failed"].append({"module": mod_name, "error": repr(e)})

    report["loaded"] = sorted(set(report["loaded"]))
    return report
