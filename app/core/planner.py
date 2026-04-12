# planner.py
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from app.core.llm_client import generate_with_ollama
from app.core.models import ToolCall


PLANNER_SYSTEM_PROMPT = """你是一个 Agent 工具规划器。

你的任务：
根据用户输入，从可用工具中选择最合适的工具，并输出 JSON 数组格式的执行计划。

严格要求：
1. 只能输出 JSON
2. 不要输出解释
3. 不要输出 markdown 代码块
4. 输出必须是一个 JSON 数组
5. 每个 step 格式必须为：
   {"id":"step1","name":"<tool_name>","args":{...}}

当前阶段限制：
- 最多输出 3 个 step
- 如果完全无法判断，才输出 []

规划原则：
1. 优先选择最可能有帮助的工具
2. 对明确请求，必须输出至少 1 个 step
3. 能单步完成就不要拆成多步
4. 只有当“先搜索再回答”明显更合理时，才输出 2 个 step

非常重要的区分规则：
1. “构建/生成/重建索引、文本块、向量” 才使用 knowledge_build_* 系列工具
2. “找、搜索、查找、看看、了解、找出来某类信息” 优先使用 knowledge_search 或 knowledge_semantic_search
3. “什么是、如何、怎么、为什么、根据知识库回答” 优先使用 knowledge_rag_answer
4. “清空、重置知识库” 才使用 knowledge_reset
5. 如果用户是在“找信息”，不要误选成“构建工具”
6. 如果用户是在“问问题”，不要误选成“构建工具”

多步规则：
- step 之间允许引用前一步结果
- 引用格式：
  "$step1.output"
  "$step1.output.hits"
  "$step1.output.answer"

可用工具清单：
- files_list：列出已上传文件
- file_meta：查看文件元信息（需要 file_id）
- file_read_by_id：按 file_id 读取原始文本（需要 file_id）
- file_parse_by_id：按 file_id 解析正文文本（需要 file_id）
- file_summary_by_id：按 file_id 生成摘要（需要 file_id）
- knowledge_build_index：构建知识索引（执行系统构建动作）
- knowledge_build_chunks：构建文本块（执行系统构建动作）
- knowledge_build_embeddings：构建知识向量（执行系统构建动作）
- knowledge_search：关键词/全文搜索
- knowledge_semantic_search：语义搜索
- knowledge_rag_answer：根据知识库直接回答问题
- knowledge_reset：清空知识库运行数据

参数要求：
- files_list: {"limit": 50}
- knowledge_search: {"query": "...", "limit": 10}
- knowledge_semantic_search: {"query": "...", "limit": 10}
- knowledge_rag_answer: {"question": "...", "top_k": 5, "max_context_chars": 4000, "model_name": "qwen2.5:7b-instruct"}
- knowledge_build_index: {}
- knowledge_build_chunks: {"limit": 500, "max_chars": 50000, "chunk_size": 800, "overlap": 120, "force": false}
- knowledge_build_embeddings: {"limit": 500, "model_name": "all-MiniLM-L6-v2", "normalize": true, "max_chunks_per_file": 5000, "force": false}
- knowledge_reset: {"reset_db": true, "reset_artifacts": true, "reset_logs": false, "reset_uploads": false}

示例1：
用户输入：列出上传文件
输出：
[{"id":"step1","name":"files_list","args":{"limit":50}}]

示例2：
用户输入：帮我找一下知识库里关于重建知识库的内容
输出：
[{"id":"step1","name":"knowledge_semantic_search","args":{"query":"重建知识库","limit":10}}]

示例3：
用户输入：根据知识库回答如何重建知识库
输出：
[{"id":"step1","name":"knowledge_rag_answer","args":{"question":"如何重建知识库","top_k":5,"max_context_chars":4000,"model_name":"qwen2.5:7b-instruct"}}]

示例4：
用户输入：先搜索知识库重建相关内容，再回答如何重建知识库
输出：
[
  {"id":"step1","name":"knowledge_semantic_search","args":{"query":"知识库重建","limit":10}},
  {"id":"step2","name":"knowledge_rag_answer","args":{"question":"如何重建知识库","top_k":5,"max_context_chars":4000,"model_name":"qwen2.5:7b-instruct","extra_context":"$step1.output.hits"}}
]
"""


def _extract_json_array(text: str) -> str:
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    m = re.search(r"\[[\s\S]*\]", s)
    if not m:
        raise ValueError("no JSON array found in planner output")
    return m.group(0)


def _validate_plan_obj(obj: Any) -> List[ToolCall]:
    if not isinstance(obj, list):
        raise ValueError("planner output must be a list")

    if len(obj) > 3:
        raise ValueError("M4.2 only allows up to 3 steps")

    plan: List[ToolCall] = []
    seen_ids = set()

    for i, step in enumerate(obj, start=1):
        if not isinstance(step, dict):
            raise ValueError("each plan step must be an object")

        step_id = step.get("id")
        name = step.get("name")
        args = step.get("args", {})

        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("step.id must be non-empty string")

        if step_id in seen_ids:
            raise ValueError(f"duplicate step.id: {step_id}")
        seen_ids.add(step_id)

        if not isinstance(name, str) or not name.strip():
            raise ValueError("step.name must be non-empty string")

        if not isinstance(args, dict):
            raise ValueError("step.args must be object")

        plan.append(ToolCall(id=step_id.strip(), name=name.strip(), args=args))

    return plan


def _filter_unknown_tools(plan: List[ToolCall], allowed_tool_names: List[str]) -> List[ToolCall]:
    allowed = set(allowed_tool_names)
    return [step for step in plan if step.name in allowed]


def plan_with_llm(
    *,
    user_input: str,
    model_name: str,
    timeout: int,
    allowed_tool_names: List[str],
) -> Tuple[List[ToolCall], Dict[str, Any]]:
    tool_list_text = "\n".join(f"- {name}" for name in allowed_tool_names)
    prompt = f"""{PLANNER_SYSTEM_PROMPT}

当前实际允许使用的工具：
{tool_list_text}

用户输入：
{user_input}

请直接输出 JSON：
"""

    raw_text = ""
    parsed_json = None
    plan: List[ToolCall] = []
    llm_out: Dict[str, Any] = {}

    try:
        llm_out = generate_with_ollama(
            prompt=prompt,
            model_name=model_name,
            timeout=timeout,
        )

        raw_text = (llm_out.get("response") or "").strip()
        if not raw_text:
            raise ValueError("empty planner output")

        json_text = _extract_json_array(raw_text)
        parsed_json = json.loads(json_text)
        plan = _validate_plan_obj(parsed_json)
        plan = _filter_unknown_tools(plan, allowed_tool_names=allowed_tool_names)

    except Exception as e:
        return [], {
            "ok": False,
            "model_name": llm_out.get("model", model_name) if isinstance(llm_out, dict) else model_name,
            "raw_text": raw_text,
            "parsed_json": parsed_json,
            "error": str(e),
        }

    return plan, {
        "ok": True,
        "model_name": llm_out.get("model", model_name),
        "raw_text": raw_text,
        "parsed_json": parsed_json,
        "error": None,
    }