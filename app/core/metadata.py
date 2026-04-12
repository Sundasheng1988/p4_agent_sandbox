# metadata.py
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional


DOMAIN_KEYWORDS = {
    "agent_system": [
        "agent", "rag", "retrieval", "rerank", "router", "routing",
        "planner", "orchestrator", "runtime", "tool", "tools",
        "embedding", "vector", "knowledge", "llm",
        "知识库", "检索", "重排", "路由", "规划器", "运行时", "工具", "向量"
    ],
    "robotics": [
        "ros", "ros2", "robot", "robotics", "grasp", "servo",
        "kinematics", "ik", "yolo", "vision", "camera", "moveit",
        "机械臂", "机器人", "抓取", "舵机", "逆运动学", "视觉", "相机"
    ],
    "autonomous_driving": [
        "autonomous", "self-driving", "selfdriving", "ad", "adas",
        "planning", "perception", "localization", "prediction",
        "ego", "lane", "trajectory",
        "自动驾驶", "感知", "规划", "定位", "预测", "轨迹", "车道"
    ],
    "ops": [
        "deploy", "deployment", "ops", "runbook", "playbook",
        "incident", "monitor", "monitoring", "alert", "service",
        "部署", "运维", "告警", "监控", "服务", "故障"
    ],
}


def normalize_file_type(filename: str, mime: str = "") -> str:
    ext = Path(filename).suffix.lower().lstrip(".")

    if ext in {"md", "markdown"}:
        return "md"
    if ext in {"txt", "text"}:
        return "txt"
    if ext == "pdf":
        return "pdf"
    if ext in {"doc", "docx"}:
        return "docx"
    if ext == "json":
        return "json"
    if ext == "csv":
        return "csv"
    if ext == "py":
        return "py"
    if ext in {"yaml", "yml"}:
        return "yaml"
    if ext:
        return ext

    mime_low = (mime or "").lower()
    if "pdf" in mime_low:
        return "pdf"
    if "word" in mime_low or "officedocument" in mime_low:
        return "docx"
    if "json" in mime_low:
        return "json"
    if "text" in mime_low:
        return "txt"

    return "bin"


def _tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    parts = re.split(r"[^a-z0-9_\-\u4e00-\u9fff]+", text)
    return [p for p in parts if p]


def infer_domain_from_text(text: str) -> Optional[str]:
    tokens = _tokenize(text)
    if not tokens:
        return None

    joined = " ".join(tokens)
    best_domain = None
    best_score = 0

    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = 0
        for kw in keywords:
            kw_low = kw.lower()
            if kw_low in joined:
                score += 1
        if score > best_score:
            best_score = score
            best_domain = domain

    if best_score <= 0:
        return None

    return best_domain


def infer_domain(filename: str, text_sample: str = "") -> str:
    from_name = infer_domain_from_text(filename)
    if from_name:
        return from_name

    from_text = infer_domain_from_text(text_sample)
    if from_text:
        return from_text

    return "general"


def build_upload_metadata(
    *,
    file_id: str,
    filename: str,
    mime: str,
    ext: str,
    size: int,
    sha256: str,
    rel_dir: str,
    raw_name: str,
    created_at: float,
    text_sample: str = "",
    source: str = "upload",
) -> Dict[str, Any]:
    file_type = normalize_file_type(filename=filename, mime=mime)
    domain = infer_domain(filename=filename, text_sample=text_sample)

    return {
        "file_id": file_id,
        "filename": filename,
        "mime": mime,
        "ext": ext,
        "size": size,
        "sha256": sha256,
        "rel_dir": rel_dir,
        "raw_name": raw_name,
        "created_at": created_at,

        # 扩展 metadata
        "source": source,
        "file_type": file_type,
        "domain": domain,
        "metadata_version": 1,
    }