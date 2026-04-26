# query_understanding.py
from dataclasses import dataclass
from typing import List
import re


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

    # ===== M0 Grounding Constraints =====
    filename: str | None = None
    doc_role: str | None = None
    section_title: str | None = None
    section_date: str | None = None


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


# =========================
# 主入口（M4.8.7 + M4.8.12）
# =========================
def analyze_query(query: str) -> QueryUnderstandingResult:
    original_query = (query or "").strip()
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
    
    constraints = extract_grounding_constraints(original_query)

    return QueryUnderstandingResult(
        original_query=original_query,
        rewritten_query=rewritten_query,
        retrieval_queries=retrieval_queries,
        query_type=query_type,
        target_domains=target_domains,
        retrieval_mode=retrieval_mode,
        routing_reason=f"type={query_type}, domains={target_domains}, constraints={constraints}",
        filename=constraints.get("filename"),
        doc_role=constraints.get("doc_role"),
        section_title=constraints.get("section_title"),
        section_date=constraints.get("section_date"),
    )