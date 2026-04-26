# skill_executor.py

from __future__ import annotations

from typing import Any, Dict, List

from app.core.artifact_generator import render_template, save_markdown_artifact
from app.core.rag_pipeline import run_rag_pipeline
from app.core.skill_loader import load_skill_from_yaml
from app.core.skill_schema import (
    SkillDefinition,
    SkillExecutionResult,
    SkillStepResult,
)


def _resolve_uses(uses: List[str], state: Dict[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    for key in uses:
        if key in state:
            data[key] = state[key]
    return data


async def _execute_rag_query_step(
    *,
    ctx,
    sandbox_root: str,
    model_name: str,
    step,
    user_input: str,
    state: Dict[str, Any],
) -> SkillStepResult:
    try:
        out = await run_rag_pipeline(
            ctx=ctx,
            sandbox_root=sandbox_root,
            question=step.prompt or user_input,
            model_name=model_name,
            top_k=8,
            max_context_chars=5000,
            extra_context={"user_request": user_input, "state": state},
        )

        answer = (out.get("answer") or "").strip()
        output_key = step.output_key or step.step_name

        return SkillStepResult(
            step_name=step.step_name,
            action=step.action,
            ok=True,
            output={
                output_key: answer,
                "_rag_raw": out,
            },
            error=None,
        )
    except Exception as e:
        return SkillStepResult(
            step_name=step.step_name,
            action=step.action,
            ok=False,
            output={},
            error=str(e),
        )


async def _execute_render_template_step(
    *,
    step,
    state: Dict[str, Any],
) -> SkillStepResult:
    try:
        data = _resolve_uses(step.uses, state)
        content = render_template(
            template_name=step.template_name or "default",
            data=data,
        )
        output_key = step.output_key or "rendered_content"

        return SkillStepResult(
            step_name=step.step_name,
            action=step.action,
            ok=True,
            output={output_key: content},
            error=None,
        )
    except Exception as e:
        return SkillStepResult(
            step_name=step.step_name,
            action=step.action,
            ok=False,
            output={},
            error=str(e),
        )


async def _execute_save_artifact_step(
    *,
    sandbox_root: str,
    skill: SkillDefinition,
    step,
    state: Dict[str, Any],
) -> SkillStepResult:
    try:
        uses_data = _resolve_uses(step.uses, state)

        if "rendered_content" in uses_data:
            content = uses_data["rendered_content"]
        else:
            # 兜底：取第一个字符串值
            content = ""
            for _, v in uses_data.items():
                if isinstance(v, str):
                    content = v
                    break

        artifact = save_markdown_artifact(
            sandbox_root=sandbox_root,
            artifact_name=skill.outputs.artifact_name,
            content=content,
        )

        output_key = step.output_key or "artifact"

        return SkillStepResult(
            step_name=step.step_name,
            action=step.action,
            ok=artifact.ok,
            output={
                output_key: {
                    "ok": artifact.ok,
                    "artifact_type": artifact.artifact_type,
                    "output_path": artifact.output_path,
                    "filename": artifact.filename,
                    "content": artifact.content,
                    "error": artifact.error,
                }
            },
            error=artifact.error,
        )
    except Exception as e:
        return SkillStepResult(
            step_name=step.step_name,
            action=step.action,
            ok=False,
            output={},
            error=str(e),
        )


async def execute_skill(
    *,
    ctx,
    sandbox_root: str,
    skill_path: str,
    user_input: str,
    model_name: str,
) -> SkillExecutionResult:
    skill = load_skill_from_yaml(skill_path)
    steps_out: List[SkillStepResult] = []
    state: Dict[str, Any] = {
        "user_input": user_input,
    }

    for step in skill.steps:
        if step.action == "rag_query":
            step_result = await _execute_rag_query_step(
                ctx=ctx,
                sandbox_root=sandbox_root,
                model_name=model_name,
                step=step,
                user_input=user_input,
                state=state,
            )
        elif step.action == "render_template":
            step_result = await _execute_render_template_step(
                step=step,
                state=state,
            )
        elif step.action == "save_artifact":
            step_result = await _execute_save_artifact_step(
                sandbox_root=sandbox_root,
                skill=skill,
                step=step,
                state=state,
            )
        else:
            step_result = SkillStepResult(
                step_name=step.step_name,
                action=step.action,
                ok=False,
                output={},
                error=f"unsupported action: {step.action}",
            )

        steps_out.append(step_result)

        if not step_result.ok:
            return SkillExecutionResult(
                ok=False,
                skill_name=skill.skill_name,
                steps=steps_out,
                outputs=state,
                artifact=None,
                error=step_result.error,
            )

        # 合并 step 输出到 state
        state.update(step_result.output)

    artifact = state.get("artifact")
    return SkillExecutionResult(
        ok=True,
        skill_name=skill.skill_name,
        steps=steps_out,
        outputs=state,
        artifact=artifact,
        error=None,
    )