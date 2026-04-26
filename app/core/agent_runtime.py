# agent_runtime.py
from __future__ import annotations

from typing import Any, Dict

from app.core.rag_pipeline import run_rag_pipeline
from app.core.workflow_runtime import execute_workflow
from app.skills import load_skills


def _route_task(user_input: str) -> Dict[str, Any]:
    text = (user_input or "").strip()

    project_status_markers = [
        "项目阶段总结",
        "项目状态",
        "阶段总结",
        "风险清单",
        "当前项目状态",
    ]

    if any(k in text for k in project_status_markers):
        return {
            "task_type": "skill",
            "skill_name": "summarize_project_status",
            "reason": "matched_project_status_keywords",
        }

    return {
        "task_type": "qa",
        "skill_name": None,
        "reason": "default_to_qa",
    }


async def run_agent_runtime(
    *,
    ctx,
    sandbox_root: str,
    user_input: str,
    model_name: str,
    top_k: int = 8,
    max_context_chars: int = 5000,
) -> Dict[str, Any]:
    task_route = _route_task(user_input)

    if task_route["task_type"] == "qa":
        rag_result = await run_rag_pipeline(
            ctx=ctx,
            sandbox_root=sandbox_root,
            question=user_input,
            model_name=model_name,
            top_k=top_k,
            max_context_chars=max_context_chars,
        )
        return {
            "ok": True,
            "mode": "qa",
            "task_route": task_route,
            "result": rag_result,
        }

    skills = load_skills()
    skill_name = task_route["skill_name"]
    spec = skills.get(skill_name)

    if spec is None:
        return {
            "ok": False,
            "mode": "skill",
            "task_route": task_route,
            "error": f"skill not found: {skill_name}",
        }

    workflow = spec.builder(user_input)

    workflow_result = await execute_workflow(
        ctx=ctx,
        sandbox_root=sandbox_root,
        workflow=workflow,
        user_input=user_input,
        model_name=model_name,
        top_k=top_k,
        max_context_chars=max_context_chars,
    )

    return {
        "ok": workflow_result.get("ok", False),
        "mode": "skill",
        "task_route": task_route,
        "workflow_name": workflow.get("workflow_name"),
        "result": workflow_result,
    }