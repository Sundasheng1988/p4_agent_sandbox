from __future__ import annotations

import inspect
from typing import Any, Dict, Callable, Optional

from app.core.policy import Policy
from app.core.audit import AuditLogger
from app.tools.spec import ToolSpec
from jsonschema import Draft202012Validator

ToolFn = Callable[[Dict[str, Any]], Any]


class ToolRegistry:
    def __init__(self):
        self._handlers: Dict[str, Callable[..., Any]] = {}
        self._specs: Dict[str, ToolSpec] = {}

    def register(self, name: str, handler: Callable[..., Any]):
        self._handlers[name] = handler

    def register_spec(self, spec: ToolSpec):
        self._specs[spec.name] = spec
        self._handlers[spec.name] = spec.handler

    def get(self, name: str) -> Callable[..., Any]:
        return self._handlers[name]

    def has(self, name: str) -> bool:
        return name in self._handlers

    def list_specs(self) -> Dict[str, ToolSpec]:
        return dict(self._specs)

    def list_names(self):
        return sorted(self._handlers.keys())
    
    def get_spec(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)
    

class SafeToolExecutor:
    """
    Single gateway for ALL tool calls.
    Enforces: policy_check -> tool_call -> tool_result (audit)
    Supports:
      - legacy tool(args)
      - new tool(ctx, args)
      - async tools
    """

    def __init__(self, policy: Policy, audit: AuditLogger, registry: ToolRegistry, ctx: Optional[Any] = None):
        self.policy = policy
        self.audit = audit
        self.registry = registry
        self.ctx = ctx
    
    def _validate_args_schema(self, name: str, args: Dict[str, Any]) -> None:
        spec = self.registry.get_spec(name) if hasattr(self.registry, "get_spec") else None
        if spec is None or not getattr(spec, "args_schema", None):
            # 没有 schema：默认不校验（兼容 legacy 工具）
            return

        schema = dict(spec.args_schema)

        # 默认禁止额外字段，避免“假成功”
        if schema.get("type", "object") == "object" and "additionalProperties" not in schema:
            schema["additionalProperties"] = False

        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(args or {}), key=lambda e: list(e.path))

        if errors:
            msgs = []
            for e in errors[:5]:
                loc = ".".join(str(x) for x in e.path) or "<root>"
                msgs.append(f"{loc}: {e.message}")
            raise ValueError(f"invalid tool args for '{name}': " + "; ".join(msgs))

    async def call(self, trace_id: str, name: str, args: Dict[str, Any]):
        args = args or {}
        decision = self.policy.check_tool(name, args)
        self.audit.write(
            trace_id,
            "policy_check",
            {
                "tool": name,
                "args": args,
                "allowed": decision.allowed,
                "risk": decision.risk,
                "reason": decision.reason,
            },
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

        # ✅ args_schema 严格校验
        try:
            self._validate_args_schema(name, args)
        except Exception as e:
            self.audit.write(trace_id, "tool_args_invalid", {"tool": name, "args": args, "error": str(e)})
            raise

        fn = self.registry.get(name)
        self.audit.write(trace_id, "tool_call", {"tool": name, "args": args})

        # --- ctx 注入（兼容老工具）---
        try:
            sig = inspect.signature(fn)
            params = list(sig.parameters.keys())
        except (TypeError, ValueError):
            params = []

        if len(params) >= 2:
            # 约定：tool(ctx, args)
            out = fn(self.ctx, args)
        else:
            # 兼容：tool(args)
            out = fn(args)

        # --- 支持 async tool ---
        if inspect.isawaitable(out):
            out = await out

        self.audit.write(trace_id, "tool_result", {"tool": name, "output": out})
        return out
    
    