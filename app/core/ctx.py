from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from app.core.storage import TaskStore
from app.core.audit import AuditLogger

@dataclass(frozen=True)
class RuntimeCtx:
    sandbox_root: str
    store: TaskStore
    audit: AuditLogger
    config: Any  # 先用 Any，后面再收敛成明确类型
    file_service: Any  # ✅ 新增：先用 Any，后续再收敛类型
