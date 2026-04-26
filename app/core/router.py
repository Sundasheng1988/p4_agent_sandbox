# app/core/router.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.query_understanding import QueryUnderstandingResult


# =========================================================
# Data Structure
# =========================================================
@dataclass
class QueryRoute:
    domains: List[str] = field(default_factory=list)
    primary_domain: Optional[str] = None
    source: Optional[str] = None
    file_type: Optional[str] = None
    strategy: str = "hybrid"
    notes: List[str] = field(default_factory=list)

    # ===== M0 Grounding Constraints =====
    filename: Optional[str] = None
    doc_role: Optional[str] = None
    section_title: Optional[str] = None
    section_date: Optional[str] = None


# =========================================================
# Utils
# =========================================================
def _contains_any(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


# =========================================================
# Legacy Router
# =========================================================
def route_query(query: str) -> QueryRoute:
    q = (query or "").strip().lower()
    route = QueryRoute()

    matched_domains: List[str] = []

    # =========================================================
    # 0) OPS（最高优先级：操作类 / runbook）
    # =========================================================
    ops_strong_keywords = [
        "deploy", "deployment", "ops", "runbook", "playbook",
        "incident", "monitor", "monitoring", "alert", "service",
        "reset", "cleanup", "clean up", "recover", "rebuild",
        "delete", "remove", "restore",

        "部署", "运维", "监控", "告警", "服务",
        "清空", "重置", "恢复", "删除", "移除", "清理",
    ]

    ops_kb_patterns = [
        "清空知识库",
        "重置知识库",
        "恢复知识库",
        "重建知识库",
        "清空知识库运行数据",
        "重置知识库运行数据",
        "删除知识库运行数据",
        "如何清空知识库",
        "怎么清空知识库",
        "如何重置知识库",
        "怎么重置知识库",
        "如何恢复知识库",
        "怎么恢复知识库",
        "如何重建知识库",
        "怎么重建知识库",
        "知识库运行数据",
        "运行数据清理",
    ]

    if _contains_any(q, ops_kb_patterns):
        matched_domains.append("ops")
        route.notes.append("matched: ops_kb_pattern")

    if ("知识库" in q or "knowledge" in q) and _contains_any(q, ops_strong_keywords):
        if "ops" not in matched_domains:
            matched_domains.append("ops")
        route.notes.append("matched: ops_with_knowledge")

    if _contains_any(q, ops_strong_keywords):
        if "ops" not in matched_domains:
            matched_domains.append("ops")
        route.notes.append("matched: ops")

    # =========================================================
    # 1) Agent System
    # =========================================================
    agent_keywords = [
        "rag", "agent", "planner", "orchestrator", "runtime",
        "retrieval", "rerank", "router", "routing", "embedding",
        "knowledge", "vector", "tool",
        "知识库", "检索", "重排", "路由", "运行时", "向量", "工具",
    ]

    if _contains_any(q, agent_keywords):
        matched_domains.append("agent_system")
        route.notes.append("matched: agent_system")

    # =========================================================
    # 2) Robotics
    # =========================================================
    robotics_keywords = [
        "ros", "ros2", "robot", "robotics", "grasp", "servo",
        "kinematics", "ik", "moveit", "yolo", "vision", "camera",
        "机械臂", "机器人", "抓取", "舵机", "逆运动学", "视觉", "相机",
    ]

    if _contains_any(q, robotics_keywords):
        matched_domains.append("robotics")
        route.notes.append("matched: robotics")

    # =========================================================
    # 3) Autonomous Driving
    # =========================================================
    ad_strong_keywords = [
        "自动驾驶", "adas", "autonomous", "self-driving", "selfdriving",
        "ego vehicle", "lane keeping", "lane detection", "bev", "occupancy",
        "车道线", "自车", "高精地图", "占用网络",
    ]

    ad_weak_keywords = [
        "planning", "perception", "localization", "trajectory",
        "感知", "规划", "定位", "轨迹",
    ]

    if _contains_any(q, ad_strong_keywords):
        matched_domains.append("autonomous_driving")
        route.notes.append("matched: autonomous_driving_strong")

    robotics_signal_keywords = [
        "ros", "ros2", "robot", "robotics", "grasp", "servo",
        "kinematics", "ik", "moveit", "yolo", "vision", "camera",
        "机械臂", "机器人", "抓取", "舵机", "逆运动学", "视觉", "相机",
    ]

    if _contains_any(q, ad_weak_keywords) and not _contains_any(q, robotics_signal_keywords):
        if "autonomous_driving" not in matched_domains:
            matched_domains.append("autonomous_driving")
        route.notes.append("matched: autonomous_driving_weak")

    # =========================================================
    # 4) 去重
    # =========================================================
    route.domains = list(dict.fromkeys(matched_domains))

    # =========================================================
    # 5) Primary Domain（优先级决策）
    # =========================================================
    priority_order = [
        "ops",
        "agent_system",
        "robotics",
        "autonomous_driving",
    ]

    for p in priority_order:
        if p in route.domains:
            route.primary_domain = p
            break

    if not route.domains:
        route.notes.append("matched: general")

    route.notes = list(dict.fromkeys(route.notes))
    return route


# =========================================================
# New Router for M4.8
# =========================================================
def build_retrieval_config(q: QueryUnderstandingResult) -> Dict[str, Any]:
    """
    基于 query_understanding 的结果，生成 retrieval config。
    这里仍复用 legacy router，作为补充兜底。
    """
    legacy_route = route_query(q.rewritten_query or q.original_query)

    # 以 query_understanding 为主，legacy router 为补充
    merged_domains = list(dict.fromkeys((q.target_domains or []) + (legacy_route.domains or [])))

    if not merged_domains:
        merged_domains = []

    retrieval_mode = q.retrieval_mode or legacy_route.strategy or "hybrid"

    notes = []
    notes.append(f"query_understanding.type={q.query_type}")
    notes.append(f"query_understanding.mode={q.retrieval_mode}")
    notes.extend(legacy_route.notes or [])

    return {
        "queries": q.retrieval_queries,
        "mode": retrieval_mode,
        "domains": merged_domains,
        "primary_domain": legacy_route.primary_domain,
        "file_type": legacy_route.file_type,
        "source": legacy_route.source,
        "routing_reason": q.routing_reason,
        "notes": list(dict.fromkeys(notes)),

        # ===== M0 Grounding Constraints =====
        "filename": q.filename,
        "doc_role": q.doc_role,
        "section_title": q.section_title,
        "section_date": q.section_date,
    }