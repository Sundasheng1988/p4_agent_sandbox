from __future__ import annotations
from app.core.config import load_config
import os

from app.core.audit import AuditLogger
from app.core.policy import Policy
from app.core.storage import TaskStore
from app.tools.base import ToolRegistry, SafeToolExecutor
from app.tools.loader import load_tool_plugins
from app.core.orchestrator import Orchestrator
from app.core.file_service import FileService
from app.core.ctx import RuntimeCtx

_cfg = load_config("/home/sundasheng/p4_agent_sandbox/config.yaml")

# singletons
_audit = AuditLogger(log_dir=_cfg.app.log_dir)
_store = TaskStore(db_path=_cfg.app.db_path)
_file_service = FileService(
    sandbox_root=_cfg.app.sandbox_root,
    store=_store,
    audit=_audit,
)

_registry = ToolRegistry()

# auto-load plugin tools
_plugin_report = load_tool_plugins(_registry)
print("[BOOT] plugins =", _plugin_report)
# --- DEBUG: show tool origin (module + file) ---
try:
    import importlib
    specs = _registry.list_specs()
    for tool_name in sorted(specs.keys()):
        handler = specs[tool_name].handler
        mod_name = getattr(handler, "__module__", None)
        mod_file = None
        if mod_name:
            try:
                mod = importlib.import_module(mod_name)
                mod_file = getattr(mod, "__file__", None)
            except Exception as e:
                mod_file = f"<import_error: {e}>"
        print(f"[BOOT] tool={tool_name} handler={handler!r} module={mod_name} file={mod_file}")
except Exception as e:
    print("[BOOT] tool origin dump failed:", e)

_audit.write("__boot__", "plugins_load", _plugin_report)
_audit.write("__boot__", "config_loaded", {"allow_tools": list(_cfg.policy.allow_tools)})

_policy = Policy(allow_tools=_cfg.policy.allow_tools)
print("[BOOT] runtime.py =", __file__)
print("[BOOT] policy.allow_tools =", _cfg.policy.allow_tools)
print("[BOOT] check file_list =", _policy.check_tool("file_list", {"path": _cfg.app.sandbox_root}))

_ctx = RuntimeCtx(
    sandbox_root=_cfg.app.sandbox_root,
    store=_store,
    audit=_audit,
    config=_cfg,
    file_service=_file_service,  # ✅ 新增
)
_tool_exec = SafeToolExecutor(policy=_policy, audit=_audit, registry=_registry, ctx=_ctx)

_orchestrator = Orchestrator(tool_exec=_tool_exec, audit=_audit, store=_store)


async def startup():
    # called by FastAPI on startup
    await _store.init()


def get_audit():
    return _audit


def get_store():
    return _store


def get_orchestrator():
    return _orchestrator


def get_registry():
    return _registry


def get_policy():
    return _policy


def get_file_service():
    return _file_service

