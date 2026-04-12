# router.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class QueryRoute:
    domain: Optional[str] = None
    source: Optional[str] = None
    file_type: Optional[str] = None
    strategy: str = "hybrid"
    notes: List[str] = field(default_factory=list)


def route_query(query: str) -> QueryRoute:
    q = (query or "").strip().lower()
    route = QueryRoute()

    # agent / rag / runtime
    if any(x in q for x in [
        "rag", "agent", "planner", "orchestrator", "runtime",
        "retrieval", "rerank", "router", "routing", "embedding",
        "knowledge", "vector", "tool",
        "知识库", "检索", "重排", "路由", "运行时", "向量", "工具"
    ]):
        route.domain = "agent_system"
        route.strategy = "hybrid"
        route.notes.append("matched: agent_system")
        return route

    # robotics
    if any(x in q for x in [
        "ros", "ros2", "robot", "robotics", "grasp", "servo",
        "kinematics", "ik", "moveit", "yolo", "vision", "camera",
        "机械臂", "机器人", "抓取", "舵机", "逆运动学", "视觉", "相机"
    ]):
        route.domain = "robotics"
        route.strategy = "hybrid"
        route.notes.append("matched: robotics")
        return route

    # autonomous driving
    if any(x in q for x in [
        "自动驾驶", "adas", "autonomous", "self-driving", "selfdriving",
        "planning", "perception", "localization", "trajectory",
        "感知", "规划", "定位", "轨迹"
    ]):
        route.domain = "autonomous_driving"
        route.strategy = "hybrid"
        route.notes.append("matched: autonomous_driving")
        return route

    # ops
    if any(x in q for x in [
        "deploy", "deployment", "ops", "runbook", "playbook",
        "incident", "monitor", "monitoring", "alert", "service",
        "部署", "运维", "监控", "告警", "服务"
    ]):
        route.domain = "ops"
        route.strategy = "hybrid"
        route.notes.append("matched: ops")
        return route

    route.domain = None
    route.strategy = "hybrid"
    route.notes.append("matched: general")
    return route