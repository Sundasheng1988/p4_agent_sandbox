# artifact_generator.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


@dataclass
class ArtifactResult:
    ok: bool
    artifact_type: str
    output_path: str
    filename: str
    content: str
    error: Optional[str] = None


def _ensure_output_dir(sandbox_root: str) -> Path:
    out_dir = Path(sandbox_root) / "artifacts" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def render_template(template_name: str, data: Dict) -> str:
    if template_name == "project_status_summary_v1":
        return f"""# 项目阶段总结

## 1. 当前阶段
{data.get("summary_answer", "")}

## 2. 当前风险
{data.get("risk_answer", "")}

## 3. 备注
- 来源：当前知识库 / roadmap / dev log / trace / 项目文档
""".strip() + "\n"

    if template_name == "dev_log_v1":
        return f"""# DEV LOG

## 日期
- {datetime.now().strftime("%Y-%m-%d")}

## 当前主线
{data.get("dev_log_answer", "")}

## 备注
- 来源：当前知识库 / 项目资料
""".strip() + "\n"

    return f"""# 输出结果

{data}
""".strip() + "\n"


def save_markdown_artifact(
    *,
    sandbox_root: str,
    artifact_name: str,
    content: str,
) -> ArtifactResult:
    out_dir = _ensure_output_dir(sandbox_root)
    filename = f"{artifact_name}_{_now_tag()}.md"
    output_path = out_dir / filename

    try:
        output_path.write_text(content, encoding="utf-8")
    except Exception as e:
        return ArtifactResult(
            ok=False,
            artifact_type="markdown",
            output_path=str(output_path),
            filename=filename,
            content=content,
            error=str(e),
        )

    return ArtifactResult(
        ok=True,
        artifact_type="markdown",
        output_path=str(output_path),
        filename=filename,
        content=content,
        error=None,
    )