# query_understanding.py
from dataclasses import dataclass
from typing import List
import re
import json
from app.core.llm_client import generate_with_ollama


# =========================
# 数据结构
# =========================
@dataclass
class QueryUnderstandingResult:
    original_query: str
    rewritten_query: str
    retrieval_queries: List[str]
    query_type: str
    target_domains: List[str]
    retrieval_mode: str
    routing_reason: str

    filename: str | None = None
    doc_role: str | None = None
    section_title: str | None = None
    section_date: str | None = None

    semantic_intent: dict | None = None
    understanding_model: str | None = None


# =========================
# Utils
# =========================
def _unique_keep_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        s = (item or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out

def extract_grounding_constraints(query: str) -> dict:
    """
    从用户问题中抽取硬约束：
    - filename
    - doc_role
    - section_title
    - section_date
    """
    text = (query or "").strip()

    constraints = {
        "filename": None,
        "doc_role": None,
        "section_title": None,
        "section_date": None,
    }

    # 1) filename: xxx.md / xxx.pdf / xxx.docx / xxx.txt
    m = re.search(r"([A-Za-z0-9_\-./\u4e00-\u9fff]+?\.(?:md|txt|pdf|docx|doc|csv|json|yaml|yml))", text)
    if m:
        constraints["filename"] = m.group(1).strip()

    # 2) doc_role
    low = text.lower()
    if "roadmap" in low or "路线图" in text or "计划" in text:
        constraints["doc_role"] = "roadmap"

    if "dev_log" in low or "dev log" in low or "开发日志" in text or "日志" in text:
        constraints["doc_role"] = "dev_log"

    # 3) section_date: 2026-03-18 / 2026/03/18
    m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})", text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        constraints["section_date"] = f"{y}-{mo:02d}-{d:02d}"

    # 4) section_title: “中 XXX 回答 / 中 XXX 的内容 / 中 XXX”
    # 示例：
    # 只根据 roadmap_m0_test.md 中 当前核心问题 回答
    # 只根据 roadmap_m0_test.md 中 当前目标 回答
    patterns = [
        r"中\s+(.+?)\s+回答",
        r"中\s+(.+?)\s+的内容",
        r"中\s+(.+?)\s*[:：]",
        r"中\s+(.+?)$",
    ]

    for p in patterns:
        m = re.search(p, text)
        if m:
            sec = m.group(1).strip()
            sec = re.sub(r"^(的|关于)", "", sec).strip()
            sec = re.sub(r"[，。,.\s]+$", "", sec).strip()

            # 避免把日期当 section_title
            if sec and not re.match(r"^20\d{2}[-/]\d{1,2}[-/]\d{1,2}$", sec):
                constraints["section_title"] = sec
                break

    return constraints


# =========================
# M4.8.2 Query Type Detection
# =========================
def detect_query_type(query: str) -> str:
    q = (query or "").lower()

    if any(k in q for k in ["区别", "对比", "不同"]):
        return "compare"

    if any(k in q for k in ["关系", "联系", "依赖", "作用"]):
        return "relation"

    if any(k in q for k in ["报错", "失败", "问题", "无法", "错误"]):
        return "troubleshooting"

    if any(k in q for k in ["如何", "怎么", "步骤", "流程", "顺序", "重建", "清空"]):
        return "process"

    if any(k in q for k in ["架构", "模块", "节点", "组成", "系统"]):
        return "architecture"

    if any(k in q for k in ["是什么", "定义", "含义"]):
        return "factual"

    return "factual"


# =========================
# M4.8.3 Rewrite（最小版）
# =========================
def rewrite_query(query: str) -> str:
    rewritten = (query or "").strip()

    noise = [
        "请问",
        "帮我",
        "麻烦你",
        "一下",
        "一下子",
        "告诉我",
        "我想知道",
    ]
    for n in noise:
        rewritten = rewritten.replace(n, "")

    return rewritten.strip()


# =========================
# M4.8.5 Domain Routing
# =========================
def detect_domains(query: str) -> List[str]:
    q = (query or "").lower()
    domains: List[str] = []

    # ops
    if any(k in q for k in [
        "知识库", "索引", "向量", "重建", "清空", "运行数据",
        "playbook", "runbook", "ops",
    ]):
        domains.append("ops")

    # agent system
    if any(k in q for k in [
        "rag", "chunk", "embedding", "retrieval", "rerank",
        "context builder", "router", "planner", "orchestrator",
        "runtime", "tool", "agent",
    ]):
        domains.append("agent_system")

    # robotics
    if any(k in q for k in [
        "机械臂", "抓取", "ik", "逆运动学", "world", "grasp",
        "yolo", "servo", "相机", "camera", "vision", "坐标变换",
        "目标检测", "运动执行",
    ]):
        domains.append("robotics")

    # autonomous driving（保留接口）
    if any(k in q for k in [
        "自动驾驶", "adas", "self-driving", "autonomous", "bev",
    ]):
        domains.append("autonomous_driving")

    if not domains:
        return []

    return _unique_keep_order(domains)


# =========================
# M4.8.6 Retrieval Mode
# =========================
def select_retrieval_mode(query_type: str) -> str:
    if query_type == "factual":
        return "keyword"
    if query_type in ["process", "compare", "relation", "architecture"]:
        return "hybrid"
    if query_type == "troubleshooting":
        return "semantic"
    return "hybrid"


# =========================
# M4.8.12 Process Query Expansion
# =========================
def _expand_process_queries(
    original_query: str,
    rewritten_query: str,
    target_domains: List[str],
) -> List[str]:
    q = (rewritten_query or original_query or "").strip()
    queries: List[str] = []

    # 1) 原始 query / rewrite
    queries.append(original_query)
    if rewritten_query and rewritten_query != original_query:
        queries.append(rewritten_query)

    # 2) 简化 query
    compact = (
        q.replace("怎么走", "")
         .replace("怎么做", "")
         .replace("如何", "")
         .replace("怎么", "")
         .replace("步骤", "")
         .replace("流程", "")
         .replace("顺序", "")
         .replace("？", "")
         .strip()
    )
    if compact:
        queries.append(compact)

    # 3) 保留一个“流程”版本
    if compact:
        queries.append(f"{compact} 流程")
        queries.append(f"{compact} 步骤")

    # =========================================================
    # robotics: 流程链条补词
    # =========================================================
    if "robotics" in target_domains:
        base = compact or q
        queries.extend([
            f"{base} 目标检测",
            f"{base} 坐标变换",
            f"{base} 逆运动学",
            f"{base} IK",
            f"{base} motion execution",
            f"{base} 抓取执行",
            f"{base} grasp pipeline",
            f"{base} inverse kinematics",
            f"{base} coordinate transformation",
            f"{base} coordinate transformation inverse kinematics",
            f"{base} YOLO 坐标变换 逆运动学 执行",
            "Step 1 Object Detection",
            "Step 2 Coordinate Transformation",
            "Step 3 Inverse Kinematics",
            "Step 4 Motion Execution",
        ])

    # =========================================================
    # ops: 流程链条补词
    # =========================================================
    if "ops" in target_domains:
        base = compact or q
        queries.extend([
            f"{base} 操作步骤",
            f"{base} 执行顺序",
            f"{base} runbook",
            f"{base} playbook",
        ])

    # =========================================================
    # agent_system: 流程链条补词
    # =========================================================
    if "agent_system" in target_domains:
        base = compact or q
        queries.extend([
            f"{base} retrieval",
            f"{base} context builder",
            f"{base} rerank",
            f"{base} pipeline",
            f"{base} 检索 上下文 生成",
        ])

    return _unique_keep_order(queries)


# =========================
# 默认 Multi-query Expansion
# =========================
def build_retrieval_queries(
    original: str,
    rewritten: str,
    query_type: str,
    target_domains: List[str],
) -> List[str]:
    if query_type == "process":
        return _expand_process_queries(
            original_query=original,
            rewritten_query=rewritten,
            target_domains=target_domains,
        )

    queries = [original]
    if rewritten != original:
        queries.append(rewritten)

    simplified = (
        rewritten.replace("如何", "")
        .replace("怎么", "")
        .replace("？", "")
        .strip()
    )
    if simplified and simplified not in queries:
        queries.append(simplified)

    return _unique_keep_order(queries)

def infer_table_intent_rule(query: str) -> dict:
    """
    通用表格意图兜底：
    识别“某个对象 + 某个字段/属性是什么”的问题。
    不绑定财报，只抽 row_entity / column_field。
    """
    q = (query or "").strip()
    q = q.replace("？", "").replace("?", "").strip()

    if not q:
        return {}

    # 常见问法：A 的 B 是什么 / A B 是什么 / A B 多少
    patterns = [
        r"^(.+?)的(.+?)(?:是什么|是多少|为多少|多少|情况|说明)$",
        r"^(.+?)(.+?)(?:是什么|是多少|为多少|多少)$",
    ]

    # 通用字段候选，不限财报
    field_words = [
        "重大变动说明",
        "形成原因说明",
        "是否具有可持续性",
        "金额",
        "期末数",
        "期初数",
        "本期数",
        "上期数",
        "占比",
        "比例",
        "原因",
        "说明",
        "状态",
        "结果",
        "日期",
        "名称",
        "类型",
        "数量",
        "金额",
        "负责人",
        "备注",
    ]

    for field in field_words:
        if field in q:
            row_entity = q.replace(field, "")
            row_entity = re.sub(r"(是什么|是多少|为多少|多少|情况|说明)$", "", row_entity)
            row_entity = row_entity.replace("的", "").strip()

            if row_entity and row_entity != field:
                return {
                    "wants_table": True,
                    "row_entity": row_entity,
                    "column_field": field,
                    "expected_chunk_type": "table_row",
                    "answer_style": "direct",
                }

    for p in patterns:
        m = re.search(p, q)
        if not m:
            continue

        row_entity = m.group(1).strip()
        column_field = m.group(2).strip()

        if row_entity and column_field:
            return {
                "wants_table": True,
                "row_entity": row_entity,
                "column_field": column_field,
                "expected_chunk_type": "table_row",
                "answer_style": "direct",
            }

    return {}

def analyze_query_with_llm(query: str, model_name: str = "qwen2.5:7b-instruct") -> dict:
    prompt = f"""
你是一个通用 RAG 查询理解器。你的任务不是回答问题，而是把用户问题解析成 JSON。

只输出 JSON，不要解释，不要 Markdown，不要代码块。

你需要判断：
1. 用户是否在问普通文本内容；
2. 用户是否在问表格中的某一行对象、某个字段/列；
3. 如果是表格问题，请抽取：
   - row_entity：用户想查的行对象、项目、实体、指标、名称
   - column_field：用户想查的字段、列名、属性、说明项
4. 不确定就填 null，不要编造。

输出 JSON schema：
{{
  "rewritten_query": "改写后的检索问题",
  "retrieval_queries": ["检索词1", "检索词2"],
  "query_type": "factual|table_lookup|compare|process|architecture|relation|troubleshooting",
  "retrieval_mode": "keyword|semantic|hybrid",
  "target_domains": [],
  "semantic_intent": {{
    "wants_table": false,
    "row_entity": null,
    "column_field": null,
    "expected_chunk_type": null,
    "answer_style": "direct"
  }}
}}

示例1：
用户问题：苹果公司的注册地址是什么
输出：
{{
  "rewritten_query": "苹果公司 注册地址",
  "retrieval_queries": ["苹果公司 注册地址", "注册地址"],
  "query_type": "factual",
  "retrieval_mode": "hybrid",
  "target_domains": [],
  "semantic_intent": {{
    "wants_table": true,
    "row_entity": "苹果公司",
    "column_field": "注册地址",
    "expected_chunk_type": "table_row",
    "answer_style": "direct"
  }}
}}

示例2：
用户问题：系统架构有哪些模块
输出：
{{
  "rewritten_query": "系统架构 模块",
  "retrieval_queries": ["系统架构 模块", "架构 组成"],
  "query_type": "architecture",
  "retrieval_mode": "hybrid",
  "target_domains": [],
  "semantic_intent": {{
    "wants_table": false,
    "row_entity": null,
    "column_field": null,
    "expected_chunk_type": null,
    "answer_style": "summary"
  }}
}}

用户问题：
{query}
""".strip()

    try:
        out = generate_with_ollama(
            prompt=prompt,
            model_name=model_name,
            timeout=120,
        )
        text = (out.get("response") or "").strip()

        text = text.replace("```json", "").replace("```", "").strip()

        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]

        data = json.loads(text)

        if not isinstance(data, dict):
            return {}

        semantic_intent = data.get("semantic_intent")
        if not isinstance(semantic_intent, dict):
            semantic_intent = {}

        # LLM 没识别出来时，用规则兜底
        rule_intent = infer_table_intent_rule(query)

        if rule_intent and not semantic_intent.get("wants_table"):
            semantic_intent = rule_intent
            data["semantic_intent"] = semantic_intent
            data["query_type"] = "table_lookup"
            data["retrieval_mode"] = "hybrid"

            row_entity = rule_intent.get("row_entity")
            column_field = rule_intent.get("column_field")
            data["rewritten_query"] = f"{row_entity} {column_field}".strip()
            data["retrieval_queries"] = _unique_keep_order([
                f"{row_entity} {column_field}",
                str(row_entity or ""),
                str(column_field or ""),
            ])

        return data

    except Exception:
        rule_intent = infer_table_intent_rule(query)
        if rule_intent:
            row_entity = rule_intent.get("row_entity")
            column_field = rule_intent.get("column_field")
            return {
                "rewritten_query": f"{row_entity} {column_field}".strip(),
                "retrieval_queries": _unique_keep_order([
                    f"{row_entity} {column_field}",
                    str(row_entity or ""),
                    str(column_field or ""),
                ]),
                "query_type": "table_lookup",
                "retrieval_mode": "hybrid",
                "target_domains": [],
                "semantic_intent": rule_intent,
            }

        return {}


# =========================
# 主入口（M4.8.7 + M4.8.12）
# =========================
def analyze_query(
    query: str,
    model_name: str = "qwen2.5:7b-instruct",
    use_llm: bool = True,
) -> QueryUnderstandingResult:
    original_query = (query or "").strip()

    llm_data = analyze_query_with_llm(original_query, model_name=model_name) if use_llm else {}

    if llm_data:
        rewritten_query = str(llm_data.get("rewritten_query") or original_query).strip()
        query_type = str(llm_data.get("query_type") or "factual").strip()
        retrieval_mode = str(llm_data.get("retrieval_mode") or "hybrid").strip()

        target_domains = llm_data.get("target_domains") or []
        if not isinstance(target_domains, list):
            target_domains = []

        retrieval_queries = llm_data.get("retrieval_queries") or []
        if not isinstance(retrieval_queries, list):
            retrieval_queries = []

        retrieval_queries = _unique_keep_order(
            [str(x).strip() for x in retrieval_queries if str(x).strip()]
        )

        semantic_intent = llm_data.get("semantic_intent") or {}
        if not isinstance(semantic_intent, dict):
            semantic_intent = {}

        if not retrieval_queries:
            row_entity = semantic_intent.get("row_entity")
            column_field = semantic_intent.get("column_field")

            if semantic_intent.get("wants_table") and row_entity and column_field:
                retrieval_queries = _unique_keep_order([
                    f"{row_entity} {column_field}",
                    str(row_entity),
                    str(column_field),
                ])
            else:
                retrieval_queries = [rewritten_query]

        constraints = extract_grounding_constraints(original_query)

        return QueryUnderstandingResult(
            original_query=original_query,
            rewritten_query=rewritten_query,
            retrieval_queries=retrieval_queries,
            query_type=query_type,
            target_domains=target_domains,
            retrieval_mode=retrieval_mode,
            routing_reason=(
                f"llm_understanding model={model_name}, "
                f"type={query_type}, intent={semantic_intent}"
            ),
            filename=constraints.get("filename"),
            doc_role=constraints.get("doc_role"),
            section_title=constraints.get("section_title"),
            section_date=constraints.get("section_date"),
            semantic_intent=semantic_intent,
            understanding_model=model_name,
        )

    rewritten_query = rewrite_query(original_query)
    query_type = detect_query_type(original_query)
    target_domains = detect_domains(rewritten_query or original_query)
    retrieval_mode = select_retrieval_mode(query_type)

    retrieval_queries = build_retrieval_queries(
        original=original_query,
        rewritten=rewritten_query,
        query_type=query_type,
        target_domains=target_domains,
    )

    rule_intent = infer_table_intent_rule(original_query)
    if rule_intent:
        query_type = "table_lookup"
        retrieval_mode = "hybrid"
        row_entity = rule_intent.get("row_entity")
        column_field = rule_intent.get("column_field")
        retrieval_queries = _unique_keep_order([
            f"{row_entity} {column_field}",
            str(row_entity or ""),
            str(column_field or ""),
        ])

    constraints = extract_grounding_constraints(original_query)

    return QueryUnderstandingResult(
        original_query=original_query,
        rewritten_query=rewritten_query,
        retrieval_queries=retrieval_queries,
        query_type=query_type,
        target_domains=target_domains,
        retrieval_mode=retrieval_mode,
        routing_reason=(
            f"rule_fallback type={query_type}, "
            f"domains={target_domains}, constraints={constraints}, intent={rule_intent}"
        ),
        filename=constraints.get("filename"),
        doc_role=constraints.get("doc_role"),
        section_title=constraints.get("section_title"),
        section_date=constraints.get("section_date"),
        semantic_intent=rule_intent or {},
        understanding_model="rule_fallback",
    )