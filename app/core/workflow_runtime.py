# workflow_runtime.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo

from app.skills.financial.pdf_parser import parse_financial_pdf
from app.skills.financial.extractor import (
    collect_financial_inputs,
    extract_financial_text,
    extract_financial_tables,
    extract_financial_evidence,
    build_financial_summary,
)
from app.skills.financial.analyzer import analyze_financial_metrics
from app.skills.financial.reporter import generate_financial_report
from app.skills.financial.reasoner import (
    extract_financial_reasons,
    verify_financial_reasons,
)
from app.skills.financial.rag_reasoner import analyze_financial_with_rag
from app.skills.financial.knowledge_adapter import register_financial_markdown

# =========================================================
# Utils
# =========================================================
def _ensure_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalize_text(text: Any) -> str:
    if text is None:
        return ""
    return str(text).strip()


def _truncate(text: str, limit: int) -> str:
    text = _normalize_text(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[内容已截断]"


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig")
        except Exception:
            return ""
    except Exception:
        return ""


def _read_uploaded_raw_file(sandbox_root: str, file_id: str, ext: str | None) -> str:
    sandbox = Path(sandbox_root)
    ext = (ext or "").lstrip(".").strip().lower()

    # 优先按 raw.<ext>
    if ext:
        p = sandbox / "uploads" / file_id / f"raw.{ext}"
        if p.exists():
            return _safe_read_text(p)

    # fallback：找 raw.*
    upload_dir = sandbox / "uploads" / file_id
    if upload_dir.exists():
        for candidate in upload_dir.glob("raw.*"):
            if candidate.is_file():
                return _safe_read_text(candidate)

    return ""


def _render_project_status_markdown(
    *,
    user_input: str,
    generated_at: str,
    current_stage: str,
    completed: str,
    in_progress: str,
    risks: str,
    next_steps: str,
    used_files: List[Dict[str, Any]],
) -> str:
    used_files_lines = []
    for item in used_files:
        used_files_lines.append(
            f"- {item.get('doc_type', 'unknown')}: {item.get('filename', '')} ({item.get('file_id', '')})"
        )

    used_files_block = "\n".join(used_files_lines) if used_files_lines else "- 无"

    return f"""# 项目阶段总结

生成时间：{generated_at}
    
## 用户任务
{user_input}

## 使用材料
{used_files_block}

## 一、当前阶段判断
{current_stage}

## 二、已完成的工作与能力
{completed}

## 三、当前正在推进的重点
{in_progress}

## 四、主要问题与风险
{risks}

## 五、下一步计划
{next_steps}
""".strip() + "\n"


def _render_project_status_markdown_from_facts(
    *,
    user_input: str,
    generated_at: str,
    facts: Dict[str, Any],
    used_files: List[Dict[str, Any]],
    summary: Dict[str, str] | None = None,
) -> str:
    def render_list(items: List[str]) -> str:
        if not items:
            return "材料中未体现。"
        return "\n".join([f"- {x}" for x in items])

    def pick_section(key: str, fallback_items: List[str]) -> str:
        if summary and _normalize_text(summary.get(key)):
            return _normalize_text(summary.get(key))
        return render_list(fallback_items)

    used_files_block = "\n".join(
        [
            f"- {item.get('doc_type', 'unknown')}: {item.get('filename', '')} ({item.get('file_id', '')})"
            for item in used_files
        ]
    ) or "- 无"

    return f"""# 项目阶段总结

生成时间：{generated_at}

## 用户任务
{user_input}

## 使用材料
{used_files_block}

## 一、当前阶段判断
{pick_section("current_stage", facts.get("current_stage", []))}

## 二、已完成的工作与能力
{pick_section("completed", facts.get("completed", []))}

## 三、当前正在推进的重点
{pick_section("in_progress", facts.get("in_progress", []))}

## 四、主要问题与风险
{pick_section("problems", facts.get("problems", []))}

## 五、下一步计划
{pick_section("next_steps", facts.get("next_steps", []))}
""".strip() + "\n"


# =========================================================
# Material Discovery
# =========================================================
def _classify_doc_type(filename: str) -> str | None:
    name = (filename or "").strip().lower()

    if not name:
        return None

    if "roadmap" in name:
        return "roadmap"

    if "dev_log" in name or "devlog" in name or "dev-log" in name:
        return "dev_log"

    if "trace" in name:
        return "trace"

    if "architecture" in name or "arch" in name:
        return "project_doc"

    return None


async def _load_candidate_files(ctx, limit: int = 200) -> List[Dict[str, Any]]:
    try:
        rows = await ctx.store.list_files(limit=limit)
        if isinstance(rows, list):
            return rows
    except Exception:
        pass
    return []


async def _select_material_files(ctx, sandbox_root: str) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    rows = await _load_candidate_files(ctx, limit=200)

    selected: List[Dict[str, Any]] = []
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "roadmap": [],
        "dev_log": [],
        "trace": [],
        "project_doc": [],
    }

    for row in rows:
        filename = str(row.get("filename") or "")
        file_id = str(row.get("file_id") or "")
        ext = str(row.get("ext") or "")

        doc_type = _classify_doc_type(filename)
        if doc_type is None:
            continue

        content = _read_uploaded_raw_file(
            sandbox_root=sandbox_root,
            file_id=file_id,
            ext=ext,
        )

        item = {
            "doc_type": doc_type,
            "file_id": file_id,
            "filename": filename,
            "ext": ext,
            "content": content,
        }

        selected.append(item)
        grouped[doc_type].append(item)

    return selected, grouped


def _build_materials_context(
    grouped: Dict[str, List[Dict[str, Any]]],
    *,
    max_chars_per_file: int = 6000,
) -> str:
    parts: List[str] = []

    ordered_types = ["roadmap", "dev_log", "trace", "project_doc"]

    for doc_type in ordered_types:
        docs = grouped.get(doc_type, []) or []
        if not docs:
            continue

        type_title = {
            "roadmap": "Roadmap",
            "dev_log": "Dev Log",
            "trace": "Trace",
            "project_doc": "Project Docs",
        }.get(doc_type, doc_type)

        parts.append(f"## {type_title}")

        for doc in docs:
            filename = doc.get("filename", "")
            file_id = doc.get("file_id", "")
            content = _truncate(doc.get("content", ""), max_chars_per_file)

            parts.append(
                f"### {filename} (file_id={file_id})\n{content if content else '[空内容或无法读取]'}"
            )

    return "\n\n".join(parts).strip()


# =========================================================
# Step Implementations
# =========================================================
async def _step_collect_materials(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    selected, grouped = await _select_material_files(ctx, sandbox_root=sandbox_root)

    materials_context = _build_materials_context(
        grouped,
        max_chars_per_file=int(step.get("max_chars_per_file", 6000)),
    )

    return {
        "ok": True,
        "used_files": [
            {
                "doc_type": x["doc_type"],
                "file_id": x["file_id"],
                "filename": x["filename"],
            }
            for x in selected
        ],
        "grouped_counts": {k: len(v) for k, v in grouped.items()},
        "materials_context": materials_context,
    }

def _extract_project_facts_from_materials(materials_context: str) -> Dict[str, Any]:
    """
    Rule-based v3:
    - 不调用 LLM
    - 只抽取材料中明确出现的事实
    - current_stage / completed / in_progress / problems / next_steps 分桶更严格
    - next_steps 只保留未完成项，不再混入当前开发重点和当前阶段任务
    """
    text = _normalize_text(materials_context)

    facts: Dict[str, Any] = {
        "current_stage": [],
        "completed": [],
        "in_progress": [],
        "problems": [],
        "next_steps": [],
    }

    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    current_section = ""

    def normalize_item(value: str) -> str:
        return (
            value.strip()
            .lstrip("-")
            .strip()
            .replace("（rule-based v1）", "")
            .strip()
        )

    def add_unique(bucket: str, value: str) -> None:
        value = value.strip().lstrip("-").strip()
        if not value:
            return

        norm = normalize_item(value)
        existed = [normalize_item(x) for x in facts[bucket]]

        if norm not in existed:
            facts[bucket].append(value)

    def is_heading_or_lead_line(value: str) -> bool:
        v = value.strip().lstrip("-").strip()

        if not v:
            return True

        lead_lines = {
            "但：",
            "但:",
            "观察到：",
            "观察到:",
            "说明：",
            "说明:",
            "当前发现：",
            "当前发现:",
            "问题逐渐明显：",
            "问题逐渐明显:",
            "围绕以下能力验证：",
            "围绕以下能力验证:",
            "开始思考：",
            "开始思考:",
            "开始测试 Agent 输出：",
            "开始测试 Agent 输出:",
            "当前系统状态：",
            "当前系统状态:",
            "file metadata 增加：",
            "file metadata 增加:",
            "chunk 开始继承：",
            "chunk 开始继承:",
            "并增加：",
            "并增加:",
        }

        if v in lead_lines:
            return True

        if v == "---":
            return True

        if v.startswith("Version:") or v.startswith("Date:"):
            return True

        if v.endswith("：") or v.endswith(":"):
            return True

        if "是否" in v:
            return True

        return False

    def clean_line(line: str) -> str:
        return line.strip().lstrip("-").strip()

    for raw_line in lines:
        line = raw_line.strip()
        clean = clean_line(line)

        if not clean:
            continue

        # Markdown section
        if clean.startswith("#"):
            current_section = clean.strip("#").strip()
            continue

        if is_heading_or_lead_line(clean):
            continue

        # 一、当前阶段判断
        if current_section in [
            "当前里程碑",
            "当前目标",
        ]:
            add_unique("current_stage", clean)
            continue

        # 二、已完成工作
        if current_section == "已完成":
            add_unique("completed", clean)
            continue

        if current_section == "Week 1（已完成）":
            add_unique("completed", clean)
            continue

        # 三、当前正在推进的重点
        if current_section == "进行中":
            add_unique("in_progress", clean)
            continue

        if current_section in [
            "M5.2 Workflow Input Binding",
            "M5.3 Step Grounding",
            "M6 Artifact 可信性",
        ]:
            add_unique("in_progress", current_section)
            continue

        if current_section == "Week 2（进行中）":
            add_unique("in_progress", clean)
            continue

        if current_section == "Week 3（当前）":
            add_unique("in_progress", clean)
            continue

        # 四、主要问题与风险
        if current_section in [
            "1. Evidence Binding 缺失",
            "2. Hallucination 风险",
            "3. 输入未结构化",
        ]:
            add_unique("problems", clean)
            continue

        problem_markers = [
            "无法",
            "不稳定",
            "缺少",
            "缺失",
            "未进入",
            "未使用",
            "未真正",
            "未严格",
            "仍为空",
            "补全行为",
            "回答容易泛化",
            "命中内容正确，但回答不稳定",
            "无法保证 grounded",
            "存在无依据生成",
        ]

        if any(k in clean for k in problem_markers):
            add_unique("problems", clean)
            continue

        # 五、下一步计划
        # 只从“未完成”段落抽取，避免混入当前开发重点
        if current_section == "未完成":
            add_unique("next_steps", clean)
            continue

    return facts

async def _step_extract_project_facts(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    materials_context = _normalize_text(
        state.get("collect_inputs", {}).get("materials_context")
    )

    if not materials_context:
        return {
            "ok": True,
            "facts": {
                "current_stage": [],
                "completed": [],
                "in_progress": [],
                "problems": [],
                "next_steps": [],
            },
            "used_materials": state.get("collect_inputs", {}).get("used_files", []),
        }

    facts = _extract_project_facts_from_materials(materials_context)

    return {
        "ok": True,
        "facts": facts,
        "used_materials": state.get("collect_inputs", {}).get("used_files", []),
    }

def _build_rewrite_summary_prompt(
    *,
    user_input: str,
    facts: Dict[str, Any],
) -> str:
    return f"""你是一个项目报告整理助手。

你的任务是把“已抽取事实”整理成更自然、正式、可读的项目阶段总结。

【最高优先级规则】
1. 只能使用“已抽取事实”中的信息。
2. 只能做：去重、合并、归类、改写表达、整理格式。
3. 不允许新增事实。
4. 不允许推断原因、影响、优先级或结论。
5. 不允许写材料中没有的模块、能力、风险、计划。
6. 如果某一类事实为空，必须写：“材料中未体现。”
7. 输出必须是 JSON，不要输出 Markdown，不要输出解释文字。

【输出 JSON 格式】
{{
  "current_stage": "string",
  "completed": "string",
  "in_progress": "string",
  "problems": "string",
  "next_steps": "string"
}}

【格式要求】
1. 每个字段必须使用 Markdown bullet list。
2. 每一项单独一行，格式为：- xxx
3. 不允许使用逗号把多个事实合并成一行。
4. 删除重复项，例如 Router / RAG Pipeline 不要重复出现。
5. 不允许新增事实。
6. 不允许写解释性总结句。

【用户任务】
{user_input}

【已抽取事实】
{facts}

请只输出合法 JSON：
""".strip()


def _parse_rewrite_json(text: str) -> Dict[str, str]:
    import json
    import re

    raw = _normalize_text(text)
    if not raw:
        return {}

    raw = re.sub(r"^```json\s*", "", raw.strip(), flags=re.IGNORECASE)
    raw = re.sub(r"^```\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw.strip())

    try:
        obj = json.loads(raw)
    except Exception:
        return {}

    if not isinstance(obj, dict):
        return {}

    def normalize_item(value: str) -> str:
        return (
            _normalize_text(value)
            .replace("（rule-based v1）", "")
            .strip()
        )

    def render_value(value: Any) -> str:
        if value is None:
            return "材料中未体现。"

        if isinstance(value, list):
            items = []
            seen = set()

            for x in value:
                s = _normalize_text(x)
                if not s:
                    continue

                # 👉 标准化（关键）
                norm = (
                    s.replace("（rule-based v1）", "")
                    .replace("（domain + retrieval mode）", "")
                    .strip()
                )

                if norm in seen:
                    continue

                seen.add(norm)
                items.append(s)

            if not items:
                return "材料中未体现。"

            return "\n".join([f"- {x}" for x in items])

        s = _normalize_text(value)
        if not s:
            return "材料中未体现。"

        return s

    out: Dict[str, str] = {}
    for key in ["current_stage", "completed", "in_progress", "problems", "next_steps"]:
        out[key] = render_value(obj.get(key))

    return out


async def _step_rewrite_summary_from_facts(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
    model_name: str,
) -> Dict[str, Any]:
    facts = state.get("extract_facts", {}).get("facts", {}) or {}
    user_input = state.get("user_input", "")

    if not facts:
        return {
            "ok": True,
            "summary": {
                "current_stage": "材料中未体现。",
                "completed": "材料中未体现。",
                "in_progress": "材料中未体现。",
                "problems": "材料中未体现。",
                "next_steps": "材料中未体现。",
            },
            "prompt": "",
        }

    from app.core.llm_client import generate_with_ollama

    prompt = _build_rewrite_summary_prompt(
        user_input=user_input,
        facts=facts,
    )

    llm_out = generate_with_ollama(
        prompt=prompt,
        model_name=model_name,
        timeout=120,
    )

    parsed = _parse_rewrite_json(llm_out.get("response", ""))

    # 如果 LLM 没有返回合法 JSON，直接 fallback 到原 facts，避免失败
    if not parsed:
        def render_list(items: List[str]) -> str:
            if not items:
                return "材料中未体现。"
            return "\n".join([f"- {x}" for x in items])

        parsed = {
            "current_stage": render_list(facts.get("current_stage", [])),
            "completed": render_list(facts.get("completed", [])),
            "in_progress": render_list(facts.get("in_progress", [])),
            "problems": render_list(facts.get("problems", [])),
            "next_steps": render_list(facts.get("next_steps", [])),
        }

    return {
        "ok": True,
        "summary": parsed,
        "prompt": prompt,
        "raw_response": llm_out.get("response", ""),
        "llm_model": llm_out.get("model", model_name),
        "done": llm_out.get("done", True),
    }

async def _step_generate_markdown_from_facts(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    filename = f"project_status_summary_{now.strftime('%Y%m%d_%H%M%S')}.md"

    facts = state.get("extract_facts", {}).get("facts", {}) or {}
    summary = state.get("rewrite_summary", {}).get("summary", {}) or {}
    used_files = state.get("collect_inputs", {}).get("used_files", []) or []
    user_input = state.get("user_input", "")

    markdown = _render_project_status_markdown_from_facts(
        user_input=user_input,
        generated_at=generated_at,
        facts=facts,
        used_files=used_files,
        summary=summary,
    )

    output_path = Path(sandbox_root) / "artifacts" / "deliverables" / filename

    _ensure_dir(output_path)
    output_path.write_text(markdown, encoding="utf-8")

    return {
        "ok": True,
        "artifact": {
            "type": "markdown",
            "path": str(output_path),
            "filename": output_path.name,
            "created_at": generated_at,
        },
        "content": markdown,
    }


async def _step_material_analyze(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
    model_name: str,
    max_context_chars: int,
) -> Dict[str, Any]:
    question = step.get("question", "").strip()
    title = step.get("title", "").strip() or step.get("key", "").strip()

    if not question:
        return {
            "ok": False,
            "error": "missing question",
        }

    materials_context = _normalize_text(
        state.get("collect_inputs", {}).get("materials_context")
    )

    if not materials_context:
        return {
            "ok": True,
            "question": question,
            "answer": "材料中未体现。",
            "prompt": "",
            "used_materials": [],
        }

    from app.core.llm_client import generate_with_ollama

    facts = _normalize_text(state.get("facts", {}).get("answer"))
    state_summary = _normalize_text(state.get("state", {}).get("answer"))

    # facts 步骤：直接读原始材料
    if step.get("key") == "facts":
        analysis_context = materials_context

    # state 步骤：优先基于 facts 归类
    elif step.get("key") == "state":
        analysis_context = f"""## Facts
    {facts if facts else "材料中未体现"}"""

    # 其他分析步骤：优先基于 state，其次 facts，避免每步重新读全文自由总结
    else:
        analysis_context = f"""## State Summary
    {state_summary if state_summary else "材料中未体现"}

    ## Facts
    {facts if facts else "材料中未体现"}"""

    bounded_context = _truncate(analysis_context, max_context_chars)
    prompt = _build_analysis_prompt(
        section_title=title,
        user_question=question,
        materials_context=bounded_context,
    )

    llm_out = generate_with_ollama(
        prompt=prompt,
        model_name=model_name,
        timeout=120,
    )

    answer = _normalize_text(llm_out.get("response"))

    if not answer:
        answer = "材料中未体现。"

    return {
        "ok": True,
        "question": question,
        "answer": answer,
        "prompt": prompt,
        "used_materials": state.get("collect_inputs", {}).get("used_files", []),
        "llm_model": llm_out.get("model", model_name),
        "done": llm_out.get("done", True),
    }


async def _step_generate_markdown(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    user_input = state.get("user_input", "")

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    filename = f"project_status_summary_{now.strftime('%Y%m%d_%H%M%S')}.md"

    current_stage = _normalize_text(state.get("current_stage", {}).get("answer"))
    completed = _normalize_text(state.get("completed", {}).get("answer"))
    in_progress = _normalize_text(state.get("in_progress", {}).get("answer"))
    risks = _normalize_text(state.get("risks", {}).get("answer"))
    next_steps = _normalize_text(state.get("next_steps", {}).get("answer"))
    used_files = state.get("collect_inputs", {}).get("used_files", []) or []

    markdown = _render_project_status_markdown(
        user_input=user_input,
        generated_at=generated_at,
        current_stage=current_stage or "材料中未体现明确阶段判断。",
        completed=completed or "材料中未体现明确已完成项。",
        in_progress=in_progress or "材料中未体现明确推进重点。",
        risks=risks or "材料中未体现明确风险项。",
        next_steps=next_steps or "材料中未体现明确下一步计划。",
        used_files=used_files,
    )

    output_path = Path(sandbox_root) / "artifacts" / "deliverables" / filename

    _ensure_dir(output_path)
    output_path.write_text(markdown, encoding="utf-8")

    return {
        "ok": True,
        "artifact": {
            "type": "markdown",
            "path": str(output_path),
            "filename": output_path.name,
            "created_at": generated_at,
        },
        "content": markdown,
    }


# =========================================================
# Workflow Executor
# =========================================================
async def execute_workflow(
    *,
    ctx,
    sandbox_root: str,
    workflow: Dict[str, Any],
    user_input: str,
    model_name: str,
    top_k: int = 8,
    max_context_chars: int = 5000,
) -> Dict[str, Any]:

    steps: List[Dict[str, Any]] = workflow.get("steps", []) or []

    state: Dict[str, Any] = {
        "user_input": user_input,
        "workflow_name": workflow.get("workflow_name"),
        "step_results": [],
    }

    # =========================
    # Skill Registry（核心）
    # =========================
    SKILL_MAP = {
        # ===== Financial Pipeline =====
        "collect_financial_inputs": collect_financial_inputs,
        "parse_financial_pdf": parse_financial_pdf,
        "extract_financial_text": extract_financial_text,
        "extract_financial_tables": extract_financial_tables,
        "extract_financial_evidence": extract_financial_evidence,
        "build_financial_summary": build_financial_summary,
        "analyze_financial_metrics": analyze_financial_metrics,
        "generate_financial_report": generate_financial_report,

        # ===== Project Analysis Pipeline =====
        "collect_materials": _step_collect_materials,
        "register_financial_markdown": register_financial_markdown,
        "extract_project_facts": _step_extract_project_facts,
        "rewrite_summary_from_facts": _step_rewrite_summary_from_facts,
        "generate_markdown_from_facts": _step_generate_markdown_from_facts,
        "analyze_financial_with_rag": analyze_financial_with_rag,

        # ===== Legacy / fallback =====
        "material_analyze": _step_material_analyze,
        "generate_markdown": _step_generate_markdown,

        # ===== Reasoning =====
        "extract_financial_reasons": extract_financial_reasons,
        "verify_financial_reasons": verify_financial_reasons,
    }

    # =========================
    # Execute Steps
    # =========================
    for step in steps:
        step_key = step.get("key", "")
        step_type = step.get("type", "")

        if not step_key:
            return {
                "ok": False,
                "error": "step missing key",
                "state": state,
            }

        fn = SKILL_MAP.get(step_type)

        if not fn:
            return {
                "ok": False,
                "error": f"unknown step type: {step_type}",
                "state": state,
            }

        try:
            # 👉 特殊处理（需要额外参数的 step）
            if step_type == "material_analyze":
                out = await fn(
                    ctx=ctx,
                    sandbox_root=sandbox_root,
                    step=step,
                    state=state,
                    model_name=model_name,
                    max_context_chars=max_context_chars,
                )
            
            elif step_type == "analyze_financial_with_rag":
                out = await fn(
                    ctx=ctx,
                    sandbox_root=sandbox_root,
                    step=step,
                    state=state,
                    model_name=model_name,
                )

            elif step_type == "rewrite_summary_from_facts":
                out = await fn(
                    ctx=ctx,
                    sandbox_root=sandbox_root,
                    step=step,
                    state=state,
                    model_name=model_name,
                )
            
            elif step_type == "extract_financial_reasons":
                out = await fn(
                    ctx=ctx,
                    sandbox_root=sandbox_root,
                    step=step,
                    state=state,
                    model_name=model_name,
                )

            else:
                out = await fn(
                    ctx=ctx,
                    sandbox_root=sandbox_root,
                    step=step,
                    state=state,
                )

        except Exception as e:
            return {
                "ok": False,
                "error": f"step exception: {step_key} -> {str(e)}",
                "state": state,
            }

        # =========================
        # Save State
        # =========================
        state[step_key] = out
        state["step_results"].append(
            {
                "key": step_key,
                "type": step_type,
                "ok": out.get("ok", False),
            }
        )

        # =========================
        # Fail Fast
        # =========================
        if not out.get("ok", False):
            return {
                "ok": False,
                "error": out.get("error", f"step failed: {step_key}"),
                "state": state,
            }

    # =========================
    # Final Output（通用版本）
    # =========================
    final_artifact = None
    final_output = ""

    # 从后往前找“最后一个有 artifact 的 step”
    for step_result in reversed(state.get("step_results", [])):
        step_key = step_result.get("key")
        step_state = state.get(step_key, {})

        if isinstance(step_state, dict) and step_state.get("artifact"):
            final_artifact = step_state.get("artifact")
            final_output = step_state.get("content", "")
            break

    return {
        "ok": True,
        "workflow_name": workflow.get("workflow_name"),
        "step_results": state.get("step_results", []),
        "state": state,
        "artifact": final_artifact,
        "final_output": final_output,
    }