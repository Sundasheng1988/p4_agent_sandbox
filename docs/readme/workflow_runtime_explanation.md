# workflow_runtime源码

# workflow_runtime.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo


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

async def _step_collect_financial_inputs(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    财报输入收集 v1：
    先读取 marker_test/output 中已经生成好的 md 和 tables。
    后续再升级为从上传文件自动解析。
    """
    base_dir = Path("/home/sundasheng/marker_test/output")
    markdown_path = base_dir / "siyuan_q1_2026.md"
    tables_dir = base_dir / "tables"

    return {
        "ok": True,
        "base_dir": str(base_dir),
        "markdown_path": str(markdown_path),
        "tables_dir": str(tables_dir),
        "markdown_exists": markdown_path.exists(),
        "tables_dir_exists": tables_dir.exists(),
    }


async def _step_extract_financial_text(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    inputs = state.get("collect_financial_inputs", {})
    markdown_path = Path(inputs.get("markdown_path", ""))

    if not markdown_path.exists():
        return {
            "ok": False,
            "error": f"financial markdown not found: {markdown_path}",
        }

    text = _safe_read_text(markdown_path)

    return {
        "ok": True,
        "text_path": str(markdown_path),
        "text_length": len(text),
        "text_preview": text[:1000],
    }


async def _step_extract_financial_tables(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    import json

    inputs = state.get("collect_financial_inputs", {})
    tables_dir = Path(inputs.get("tables_dir", ""))

    if not tables_dir.exists():
        return {
            "ok": False,
            "error": f"financial tables dir not found: {tables_dir}",
        }

    tables = []

    for csv_path in sorted(tables_dir.glob("*.csv")):
        json_path = csv_path.with_suffix(".json")

        table_info = {
            "csv": str(csv_path),
            "json": str(json_path) if json_path.exists() else "",
            "filename": csv_path.name,
        }

        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                table_info["rows"] = len(data) if isinstance(data, list) else 0
            except Exception:
                table_info["rows"] = 0
        else:
            table_info["rows"] = 0

        tables.append(table_info)

    return {
        "ok": True,
        "table_count": len(tables),
        "tables": tables,
    }


async def _step_build_financial_summary(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    import csv

    inputs = state.get("collect_financial_inputs", {})
    tables_dir = Path(inputs.get("tables_dir", ""))

    if not tables_dir.exists():
        return {
            "ok": False,
            "error": f"financial tables dir not found: {tables_dir}",
        }

    target_table = tables_dir / "page_1_table_1.csv"

    if not target_table.exists():
        return {
            "ok": False,
            "error": f"main financial table not found: {target_table}",
        }

    summary: Dict[str, Any] = {
        "company": "思源电气",
        "period": "2026Q1",
        "source_table": str(target_table),
        "metrics": {},
    }

    current_columns: List[str] = []

    def to_number(value: str) -> Any:
        raw = str(value).strip()
        if not raw:
            return None

        cleaned = raw.replace(",", "").replace("%", "").strip()

        try:
            num = float(cleaned)
        except Exception:
            return raw

        if "%" in raw:
            return {
                "value": num,
                "unit": "%",
                "raw": raw,
            }

        return {
            "value": num,
            "raw": raw,
        }

    with target_table.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)

        for row in reader:
            row = [x.strip() for x in row]
            if not any(row):
                continue

            if row[0] == "":
                current_columns = row[1:]
                continue

            metric_name = row[0].replace("\n", "").strip()
            values = row[1:]

            if not metric_name:
                continue

            summary["metrics"][metric_name] = {
                current_columns[i] if i < len(current_columns) else f"value_{i + 1}": to_number(v)
                for i, v in enumerate(values)
            }

    return {
        "ok": True,
        "financial_summary": summary,
    }


async def _step_collect_financial_inputs(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    财报输入收集 v1：
    先读取 marker_test/output 中已经生成好的 md 和 tables。
    后续再升级为从上传文件自动解析。
    """
    base_dir = Path("/home/sundasheng/marker_test/output")
    markdown_path = base_dir / "siyuan_q1_2026.md"
    tables_dir = base_dir / "tables"

    return {
        "ok": True,
        "base_dir": str(base_dir),
        "markdown_path": str(markdown_path),
        "tables_dir": str(tables_dir),
        "markdown_exists": markdown_path.exists(),
        "tables_dir_exists": tables_dir.exists(),
    }


async def _step_extract_financial_text(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    inputs = state.get("collect_financial_inputs", {})
    markdown_path = Path(inputs.get("markdown_path", ""))

    if not markdown_path.exists():
        return {
            "ok": False,
            "error": f"financial markdown not found: {markdown_path}",
        }

    text = _safe_read_text(markdown_path)

    return {
        "ok": True,
        "text_path": str(markdown_path),
        "text_length": len(text),
        "text_preview": text[:1000],
    }


async def _step_extract_financial_tables(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    import json

    inputs = state.get("collect_financial_inputs", {})
    tables_dir = Path(inputs.get("tables_dir", ""))

    if not tables_dir.exists():
        return {
            "ok": False,
            "error": f"financial tables dir not found: {tables_dir}",
        }

    tables = []

    for csv_path in sorted(tables_dir.glob("*.csv")):
        json_path = csv_path.with_suffix(".json")

        table_info = {
            "csv": str(csv_path),
            "json": str(json_path) if json_path.exists() else "",
            "filename": csv_path.name,
        }

        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                table_info["rows"] = len(data) if isinstance(data, list) else 0
            except Exception:
                table_info["rows"] = 0
        else:
            table_info["rows"] = 0

        tables.append(table_info)

    return {
        "ok": True,
        "table_count": len(tables),
        "tables": tables,
    }


async def _step_build_financial_summary(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    import csv

    inputs = state.get("collect_financial_inputs", {})
    tables_dir = Path(inputs.get("tables_dir", ""))

    if not tables_dir.exists():
        return {
            "ok": False,
            "error": f"financial tables dir not found: {tables_dir}",
        }

    target_table = tables_dir / "page_1_table_1.csv"

    if not target_table.exists():
        return {
            "ok": False,
            "error": f"main financial table not found: {target_table}",
        }

    summary: Dict[str, Any] = {
        "company": "思源电气",
        "period": "2026Q1",
        "source_table": str(target_table),
        "metrics": {},
    }

    current_columns: List[str] = []

    def to_number(value: str) -> Any:
        raw = str(value).strip()
        if not raw:
            return None

        cleaned = raw.replace(",", "").replace("%", "").strip()

        try:
            num = float(cleaned)
        except Exception:
            return raw

        if "%" in raw:
            return {
                "value": num,
                "unit": "%",
                "raw": raw,
            }

        return {
            "value": num,
            "raw": raw,
        }

    with target_table.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)

        for row in reader:
            row = [x.strip() for x in row]
            if not any(row):
                continue

            if row[0] == "":
                current_columns = row[1:]
                continue

            metric_name = row[0].replace("\n", "").strip()
            values = row[1:]

            if not metric_name:
                continue

            summary["metrics"][metric_name] = {
                current_columns[i] if i < len(current_columns) else f"value_{i + 1}": to_number(v)
                for i, v in enumerate(values)
            }

    return {
        "ok": True,
        "financial_summary": summary,
    }


async def _step_generate_financial_report(
    *,
    ctx,
    sandbox_root: str,
    step: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    summary = state.get("build_financial_summary", {}).get("financial_summary", {})
    metrics = summary.get("metrics", {}) if isinstance(summary, dict) else {}

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    generated_at = now.strftime("%Y-%m-%d %H:%M:%S")
    filename = f"financial_report_{now.strftime('%Y%m%d_%H%M%S')}.md"

    def render_metric(name: str) -> str:
        item = metrics.get(name)
        if not item:
            return f"- {name}：材料中未体现。"

        parts = []
        for k, v in item.items():
            if isinstance(v, dict):
                parts.append(f"{k}={v.get('raw', v.get('value'))}")
            else:
                parts.append(f"{k}={v}")

        return f"- {name}：" + "；".join(parts)

    markdown = f"""# 财务分析报告

生成时间：{generated_at}

## 一、报告对象
- 公司：{summary.get("company", "材料中未体现")}
- 报告期：{summary.get("period", "材料中未体现")}
- 数据来源：{summary.get("source_table", "材料中未体现")}

## 二、核心财务指标
{render_metric("营业收入（元）")}
{render_metric("归属于上市公司股东的净利润（元）")}
{render_metric("归属于上市公司股东的扣除非经常性损益的净利润（元）")}
{render_metric("经营活动产生的现金流量净额（元）")}
{render_metric("基本每股收益（元/股）")}
{render_metric("加权平均净资产收益率")}
{render_metric("总资产（元）")}
{render_metric("归属于上市公司股东的所有者权益（元）")}

## 三、初步分析
- 营业收入、归母净利润、扣非归母净利润、经营活动现金流等核心指标已从财报首页表格中抽取。
- 本版本为规则抽取版，仅基于结构化表格生成，不进行额外推断。
- 如需进一步分析增长质量、现金流质量和资产负债变化，需要继续接入三大报表的结构化字段。

## 四、风险提示
- 当前分析只使用已抽取表格中的明确数据。
- PDF 表格解析可能存在换行、列名错位或字段合并问题，正式分析前需要校验 CSV/JSON。
""".strip() + "\n"

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

def _build_analysis_prompt(
    *,
    section_title: str,
    user_question: str,
    materials_context: str,
) -> str:
    return f"""你是一个项目分析助理。

你的任务不是自由发挥，而是严格基于“项目材料”输出结论。

要求：
1. 必须使用中文
2. 必须优先依据材料作答
3. 如果材料不足，明确写“材料中未体现”或“当前材料不足以判断”
4. 不要编造不存在的模块、计划、里程碑、风险或进展
5. 不要输出 JSON、代码、日志原文
6. 语言简洁、正式、适合项目汇报

当前分析部分：{section_title}

用户问题：
{user_question}

项目材料：
{materials_context}

请直接输出该部分的正式内容：
""".strip()


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

    for step in steps:
        step_key = step.get("key", "")
        step_type = step.get("type", "")

        if not step_key:
            return {
                "ok": False,
                "error": "step missing key",
                "state": state,
            }

        if step_type == "collect_materials":
            out = await _step_collect_materials(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )

        elif step_type == "material_analyze":
            out = await _step_material_analyze(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
                model_name=model_name,
                max_context_chars=max_context_chars,
            )
        
        elif step_type == "extract_project_facts":
            out = await _step_extract_project_facts(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )
        
        elif step_type == "rewrite_summary_from_facts":
            out = await _step_rewrite_summary_from_facts(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
                model_name=model_name,
            )

        elif step_type == "generate_markdown_from_facts":
            out = await _step_generate_markdown_from_facts(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )

        elif step_type == "collect_financial_inputs":
            out = await _step_collect_financial_inputs(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )

        elif step_type == "extract_financial_text":
            out = await _step_extract_financial_text(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )

        elif step_type == "extract_financial_tables":
            out = await _step_extract_financial_tables(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )

        elif step_type == "build_financial_summary":
            out = await _step_build_financial_summary(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )

        elif step_type == "generate_financial_report":
            out = await _step_generate_financial_report(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )
        

        elif step_type == "generate_markdown":
            out = await _step_generate_markdown(
                ctx=ctx,
                sandbox_root=sandbox_root,
                step=step,
                state=state,
            )

        else:
            return {
                "ok": False,
                "error": f"unknown step type: {step_type}",
                "state": state,
            }

        state[step_key] = out
        state["step_results"].append(
            {
                "key": step_key,
                "type": step_type,
                "ok": out.get("ok", False),
            }
        )

        if not out.get("ok", False):
            return {
                "ok": False,
                "error": out.get("error", f"step failed: {step_key}"),
                "state": state,
            }

    final_artifact = state.get("generate_report", {}).get("artifact")
    final_output = state.get("generate_report", {}).get("content", "")

    return {
        "ok": True,
        "workflow_name": workflow.get("workflow_name"),
        "step_results": state.get("step_results", []),
        "state": state,
        "artifact": final_artifact,
        "final_output": final_output,
    }

# workflow_runtime.py 运行机制说明

> 适用文件：`app/core/workflow_runtime.py`  
> 当前用途：支撑项目总结 workflow 和财报分析 workflow 的顺序执行。

---

## 1. 这个文件的核心作用

`workflow_runtime.py` 是你的 Agent 系统里的 **Workflow 执行器**。

它不负责判断用户要做什么，也不负责直接和用户交互，而是负责：

```text
接收一个 workflow 定义
↓
按 steps 顺序执行
↓
每一步产生 output
↓
把 output 存入 state
↓
后续 step 可以读取前面 step 的结果
↓
最终生成 artifact / final_output
```

一句话：

> `workflow_runtime.py` 是“任务型 Agent”的执行引擎。

---

## 2. 它在整个系统中的位置

当前完整链路是：

```text
用户输入
↓
/agent/run 接口
↓
agent_runtime.py
↓
task_router.py 判断任务类型
↓
如果是 qa：走 rag_pipeline.py
如果是 skill：走 workflow_runtime.py
↓
workflow_runtime.py 执行 workflow steps
↓
生成 Markdown 文件 / 返回结果
```

例如财报分析：

```text
用户：请分析思源电气2026一季度财报
↓
task_router.py 命中 analyze_financial_report
↓
agent_runtime.py 加载该 skill
↓
skill 返回 workflow 定义
↓
workflow_runtime.py 执行财报 workflow
↓
生成 financial_report_xxx.md
```

---

## 3. workflow 是什么？

workflow 本质是一个 Python 字典，里面有：

```python
{
    "workflow_name": "analyze_financial_report_workflow",
    "steps": [
        {"key": "collect_financial_inputs", "type": "collect_financial_inputs"},
        {"key": "extract_financial_text", "type": "extract_financial_text"},
        {"key": "extract_financial_tables", "type": "extract_financial_tables"},
        {"key": "build_financial_summary", "type": "build_financial_summary"},
        {"key": "generate_report", "type": "generate_financial_report"},
    ]
}
```

其中：

| 字段 | 作用 |
|---|---|
| `workflow_name` | workflow 名称 |
| `steps` | 要执行的步骤列表 |
| `key` | 这一步结果存在 state 里的名字 |
| `type` | 这一步调用哪个执行函数 |

---

## 4. `key` 和 `type` 的区别

这是最容易混的地方。

### `type`

`type` 决定执行哪个函数。

例如：

```python
{"key": "generate_report", "type": "generate_financial_report"}
```

这里的 `type = generate_financial_report` 会进入：

```python
elif step_type == "generate_financial_report":
    out = await _step_generate_financial_report(...)
```

### `key`

`key` 决定这一步结果存到 `state` 的哪个字段。

例如：

```python
state["generate_report"] = out
```

你的 `execute_workflow()` 最后固定读取：

```python
final_artifact = state.get("generate_report", {}).get("artifact")
final_output = state.get("generate_report", {}).get("content", "")
```

所以最后一步建议必须使用：

```python
{"key": "generate_report", "type": "generate_financial_report"}
```

否则 workflow 虽然能执行，但最终 `artifact` 和 `final_output` 可能为空。

---

## 5. `state` 是什么？

`state` 是 workflow 执行期间的共享状态。

初始化时：

```python
state = {
    "user_input": user_input,
    "workflow_name": workflow.get("workflow_name"),
    "step_results": [],
}
```

执行每一步后：

```python
state[step_key] = out
```

所以财报 workflow 跑完后，state 大概是：

```python
{
    "user_input": "请分析思源电气2026一季度财报...",
    "workflow_name": "analyze_financial_report_workflow",
    "step_results": [...],

    "collect_financial_inputs": {...},
    "extract_financial_text": {...},
    "extract_financial_tables": {...},
    "build_financial_summary": {...},
    "generate_report": {...},
}
```

后面的 step 可以读取前面的结果，例如：

```python
inputs = state.get("collect_financial_inputs", {})
tables_dir = Path(inputs.get("tables_dir", ""))
```

这就是 step 之间传递数据的机制。

---

## 6. 主函数：`execute_workflow()` 怎么运行？

核心逻辑如下：

```text
读取 workflow.steps
↓
创建 state
↓
for step in steps:
    读取 step.key 和 step.type
    根据 type 选择对应的 _step_xxx 函数
    执行函数，得到 out
    state[key] = out
    记录 step_results
    如果 out.ok 为 False，立即中断
↓
读取 state["generate_report"] 作为最终产物
↓
返回完整结果
```

伪代码：

```python
for step in steps:
    if step_type == "collect_materials":
        out = await _step_collect_materials(...)

    elif step_type == "collect_financial_inputs":
        out = await _step_collect_financial_inputs(...)

    elif step_type == "generate_financial_report":
        out = await _step_generate_financial_report(...)

    else:
        return {"ok": False, "error": "unknown step type"}

    state[step_key] = out

    if not out.get("ok"):
        return {"ok": False, "error": ...}
```

---

## 7. 财报 workflow 是怎么运行的？

当前财报 workflow 有 5 步。

---

### Step 1：`collect_financial_inputs`

执行函数：

```python
_step_collect_financial_inputs()
```

当前作用：

```text
固定读取 marker_test/output 目录
```

读取路径：

```text
/home/sundasheng/marker_test/output/siyuan_q1_2026.md
/home/sundasheng/marker_test/output/tables/
```

输出：

```python
{
    "ok": True,
    "base_dir": "...",
    "markdown_path": ".../siyuan_q1_2026.md",
    "tables_dir": ".../tables",
    "markdown_exists": True,
    "tables_dir_exists": True,
}
```

当前版本没有从 DB 或上传文件读取，因为它是 v1 验证版。

---

### Step 2：`extract_financial_text`

执行函数：

```python
_step_extract_financial_text()
```

它从上一步拿到：

```python
state["collect_financial_inputs"]["markdown_path"]
```

然后读取 Markdown 文本。

输出：

```python
{
    "ok": True,
    "text_path": "...",
    "text_length": 22000,
    "text_preview": "前1000字符..."
}
```

当前这个 step 只是确认文本能读到，后面可以升级为抽取管理层讨论、重要事项等内容。

---

### Step 3：`extract_financial_tables`

执行函数：

```python
_step_extract_financial_tables()
```

它读取：

```text
/home/sundasheng/marker_test/output/tables/*.csv
/home/sundasheng/marker_test/output/tables/*.json
```

输出所有表格列表：

```python
{
    "ok": True,
    "table_count": 13,
    "tables": [
        {"filename": "page_1_table_1.csv", "rows": ...},
        ...
    ]
}
```

当前作用是证明表格结构化结果已经存在。

---

### Step 4：`build_financial_summary`

执行函数：

```python
_step_build_financial_summary()
```

当前读取核心表：

```text
page_1_table_1.csv
```

这个表是财报首页的主要财务数据表，包含：

- 营业收入
- 归母净利润
- 扣非归母净利润
- 经营活动现金流净额
- EPS
- ROE
- 总资产
- 归母净资产

输出结构化数据：

```python
{
    "ok": True,
    "financial_summary": {
        "company": "思源电气",
        "period": "2026Q1",
        "source_table": ".../page_1_table_1.csv",
        "metrics": {
            "营业收入（元）": {
                "本报告期": {"value": 4568663867.62, "raw": "4,568,663,867.62"},
                "上年同期": {"value": 3226557969.19, "raw": "3,226,557,969.19"},
                "本报告期比上年同期增减（%）": {"value": 41.60, "unit": "%", "raw": "41.60%"}
            }
        }
    }
}
```

这是财报分析 skill 的核心数据基础。

---

### Step 5：`generate_financial_report`

执行函数：

```python
_step_generate_financial_report()
```

它读取：

```python
state["build_financial_summary"]["financial_summary"]
```

然后渲染 Markdown。

输出文件：

```text
artifacts/deliverables/financial_report_YYYYMMDD_HHMMSS.md
```

同时返回：

```python
{
    "ok": True,
    "artifact": {
        "type": "markdown",
        "path": "...",
        "filename": "financial_report_xxx.md",
        "created_at": "..."
    },
    "content": "# 财务分析报告..."
}
```

---

## 8. 为什么现在不需要上传到 DB？

因为当前财报 workflow v1 不是 RAG 路线，而是文件处理路线。

### RAG 路线

```text
上传文件
↓
写入 files 表
↓
chunk
↓
embedding
↓
retrieval
↓
LLM 问答
```

适合：

```text
对大量文档自由问答
```

### 财报 Skill 路线

```text
读取固定文件
↓
读取 CSV 表格
↓
规则抽取指标
↓
生成 Markdown 报告
```

适合：

```text
固定任务处理和结构化产物生成
```

所以当前版本不需要 DB，是因为它直接读本地解析结果。

后续正式版本应该变成：

```text
上传 PDF
↓
DB 记录 file_id
↓
workflow 根据 file_id 找 PDF
↓
PyMuPDF / Marker 抽文本
↓
pdfplumber 抽表
↓
build_financial_summary
↓
generate_financial_report
```

---

## 9. 当前代码里需要注意的问题

你当前贴出的代码中，下面这些函数重复定义了两次：

```python
_step_collect_financial_inputs
_step_extract_financial_text
_step_extract_financial_tables
_step_build_financial_summary
```

Python 会以后面那一版为准，不一定立刻报错，但代码不干净。

建议后续清理成：

```text
每个函数只保留一份
```

否则以后修改前一份函数时，实际运行的可能还是后一份，容易误判。

---

## 10. 当前版本的优点

当前版本的最大优点是：

```text
确定性强、无幻觉、可验证
```

它不是让 LLM 自己猜财报内容，而是：

```text
CSV 明确有什么
↓
summary 就抽什么
↓
report 就写什么
```

这符合你之前一直强调的 grounded 原则。

---

## 11. 当前版本的不足

当前生成的报告还偏“数据罗列”，不是完整分析。

目前已经能输出：

```text
营业收入是多少
净利润是多少
同比多少
现金流是多少
```

但还没有分析：

```text
收入增速 vs 利润增速
成本增速是否高于收入
毛利率是否变化
经营现金流质量
投资现金流变化
资产负债结构变化
费用率变化
```

下一步应该增加：

```python
_step_analyze_financial_metrics()
```

放在：

```text
build_financial_summary
↓
analyze_financial_metrics
↓
generate_financial_report
```

---

## 12. 推荐的下一步改造

### 新增 step

```python
elif step_type == "analyze_financial_metrics":
    out = await _step_analyze_financial_metrics(...)
```

### workflow 变成

```python
"steps": [
    {"key": "collect_financial_inputs", "type": "collect_financial_inputs"},
    {"key": "extract_financial_text", "type": "extract_financial_text"},
    {"key": "extract_financial_tables", "type": "extract_financial_tables"},
    {"key": "build_financial_summary", "type": "build_financial_summary"},
    {"key": "analyze_financial_metrics", "type": "analyze_financial_metrics"},
    {"key": "generate_report", "type": "generate_financial_report"},
]
```

### 分析规则示例

```text
如果收入同比 > 30%：收入高速增长
如果净利润增速 < 收入增速：利润率可能承压
如果经营现金流为负：现金流质量需要关注
如果营业成本增速 > 收入增速：毛利率可能下降
```

---

## 13. 一句话总结

`workflow_runtime.py` 当前已经实现了一个最小可用的任务型 Agent 执行器。

它可以把：

```text
Skill 定义
↓
Workflow steps
↓
本地文件/表格处理
↓
结构化数据抽取
↓
Markdown 产物生成
```

串成完整闭环。

这说明你的系统已经从：

```text
RAG 问答系统
```

升级为：

```text
可执行任务、可生成产物的 Agent Runtime
```
