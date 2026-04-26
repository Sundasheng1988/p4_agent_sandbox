# metadata.py
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timezone, timedelta


# ===== domain =====

DOMAIN_KEYWORDS = {
    "agent_system": ["agent", "rag", "retrieval", "router", "planner", "llm", "知识库"],
    "robotics": ["ros", "robot", "servo", "ik", "机械臂"],
    "autonomous_driving": ["autonomous", "planning", "perception", "自动驾驶"],
    "ops": ["deploy", "monitor", "alert", "运维"],
}


def normalize_file_type(filename: str, mime: str = "") -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    return ext or "bin"


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", (text or "").lower())


def infer_domain(filename: str, text_sample: str = "") -> str:
    text = filename + " " + text_sample
    tokens = _tokenize(text)
    joined = " ".join(tokens)

    best = None
    best_score = 0

    for domain, kws in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in joined)
        if score > best_score:
            best_score = score
            best = domain

    return best or "general"


# ===== doc_role =====

def infer_doc_role(filename: str, text_sample: str = "") -> str:
    name = (filename or "").lower()

    if "roadmap" in name:
        return "roadmap"
    if "dev_log" in name or "devlog" in name:
        return "dev_log"
    if "trace" in name:
        return "trace"
    if "meeting" in name or "minutes" in name or "纪要" in name:
        return "meeting_notes"
    if "architecture" in name or "design" in name:
        return "project_doc"

    return "general"


# ===== extra extract =====

def extract_milestone(text: str) -> Optional[str]:
    m = re.search(r"\bM\d+(?:\.\d+)?\b", text, re.IGNORECASE)
    return m.group(0) if m else None


def extract_version(text: str) -> Optional[str]:
    m = re.search(r"\bv\d+(?:\.\d+)*\b", text, re.IGNORECASE)
    return m.group(0) if m else None


def extract_project_name(text: str) -> Optional[str]:
    lines = text.splitlines()
    for ln in lines[:10]:
        if "roadmap" in ln.lower() or "agent" in ln.lower():
            return ln.strip()[:50]
    return None


# ===== main =====

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

    # 时间
    dt = datetime.fromtimestamp(created_at, tz=timezone(timedelta(hours=8)))
    created_at_iso = dt.isoformat()
    created_date = dt.strftime("%Y-%m-%d")

    # 推断
    file_type = normalize_file_type(filename, mime)
    domain = infer_domain(filename, text_sample)
    doc_role = infer_doc_role(filename, text_sample)

    milestone = extract_milestone(text_sample)
    version_tag = extract_version(text_sample)
    project_name = extract_project_name(text_sample)

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
        "created_at_iso": created_at_iso,
        "created_date": created_date,

        "source": source,
        "file_type": file_type,
        "domain": domain,

        "doc_role": doc_role,
        "project_name": project_name,
        "milestone": milestone,
        "version_tag": version_tag,

        "metadata_version": 2,
    }