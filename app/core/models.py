# models.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field

Risk = Literal["low", "medium", "high"]


class ToolCall(BaseModel):
    name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    id: Optional[str] = None


class StepResult(BaseModel):
    ok: bool
    output: Any = None
    error: Optional[str] = None


class TaskRequest(BaseModel):
    user_input: str
    # allow_tools: List[str] = Field(default_factory=list)
    debug: bool = False


class TaskState(BaseModel):
    trace_id: str
    user_input: str
    status: str
    plan: List[ToolCall] = Field(default_factory=list)
    step_results: List[StepResult] = Field(default_factory=list)
    final_answer: str = ""
    # final_answer: Optional[str] = None
    # status: Literal["planning", "executing", "verifying", "reporting", "done", "failed"] = "planning"

    # 👇 新增
    verify_result: Optional[Dict[str, Any]] = None
    verify_result_after_retry: Optional[Dict[str, Any]] = None

