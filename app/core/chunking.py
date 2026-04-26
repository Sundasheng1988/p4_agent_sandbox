# chunking.py
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional


def _normalize_text(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _is_markdown(filename: str) -> bool:
    return (filename or "").lower().endswith(".md")


def _to_iso_datetime(ts: Any) -> Optional[str]:
    try:
        if ts is None:
            return None
        return datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds")
    except Exception:
        return None


def _to_date_str(ts: Any) -> Optional[str]:
    try:
        if ts is None:
            return None
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except Exception:
        return None


def _extract_date_from_text(text: str) -> Optional[str]:
    s = _normalize_text(text)

    # 2026-03-15 / 2026/03/15 / 2026.03.15
    m = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    # 2026年3月15日
    m = re.search(r"\b(20\d{2})年(\d{1,2})月(\d{1,2})日\b", s)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    return None


def _infer_doc_role(
    filename: str,
    section_title: str,
    section_path: List[str],
    body: str,
    file_meta: Optional[Dict[str, Any]] = None,
) -> str:
    # 1) 优先使用 file_meta 中已有值
    meta_role = (file_meta or {}).get("doc_role")
    if meta_role and meta_role != "general":
        return meta_role

    name = (filename or "").lower()
    title = (section_title or "").lower()
    path = " > ".join(section_path or []).lower()
    text = f"{name}\n{title}\n{path}\n{body}".lower()

    if "roadmap" in text or "路线图" in text:
        return "roadmap"

    if "dev log" in text or "开发记录" in text or "开发日志" in text:
        return "dev_log"

    if "trace" in text or "执行轨迹" in text:
        return "trace"

    if any(k in text for k in ["会议纪要", "meeting notes", "meeting", "minutes"]):
        return "meeting_notes"

    if any(k in text for k in ["任务描述", "action items", "todo", "owner", "due date"]):
        return "task_brief"

    if any(k in text for k in ["架构", "architecture", "设计文档", "project doc"]):
        return "project_doc"

    return "general"


def _extract_people(text: str) -> List[str]:
    s = _normalize_text(text)
    people: List[str] = []

    # Owner: Alice / 负责人：张三
    patterns = [
        r"(?:owner|负责人|责任人)[:：]\s*([A-Za-z\u4e00-\u9fff·_\- ]{2,30})",
        r"(?:由|assigned to)\s*([A-Za-z\u4e00-\u9fff·_\- ]{2,30})\s*(?:负责|处理)?",
    ]

    for pat in patterns:
        for m in re.finditer(pat, s, flags=re.IGNORECASE):
            name = m.group(1).strip(" .,:;，。；：")
            if name and name not in people:
                people.append(name)

    return people[:10]


def _extract_due_dates(text: str) -> List[str]:
    s = _normalize_text(text)
    out: List[str] = []

    for m in re.finditer(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", s):
        y, mo, d = m.groups()
        val = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        if val not in out:
            out.append(val)

    for m in re.finditer(r"\b(20\d{2})年(\d{1,2})月(\d{1,2})日\b", s):
        y, mo, d = m.groups()
        val = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
        if val not in out:
            out.append(val)

    return out[:10]


def _extract_action_items(text: str) -> List[str]:
    s = _normalize_text(text)
    lines = [ln.strip("-•* \t") for ln in s.splitlines() if ln.strip()]
    items: List[str] = []

    for ln in lines:
        low = ln.lower()
        if any(
            k in low for k in [
                "待办", "todo", "action", "行动项", "下一步", "需要",
                "应当", "计划", "follow up", "owner", "due"
            ]
        ):
            items.append(ln)

    return items[:10]


def _split_markdown_sections(text: str) -> List[Dict[str, Any]]:
    text = _normalize_text(text)
    if not text:
        return []

    lines = text.split("\n")
    heading_re = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

    sections: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    heading_stack: List[Optional[str]] = [None] * 6

    def close_current() -> None:
        nonlocal current
        if current is None:
            return
        current["body"] = _normalize_text("\n".join(current.pop("body_lines", [])))
        sections.append(current)
        current = None

    for line in lines:
        m = heading_re.match(line)
        if m:
            close_current()

            level = len(m.group(1))
            title = m.group(2).strip()

            heading_stack[level - 1] = title
            for i in range(level, 6):
                heading_stack[i] = None

            section_path = [x for x in heading_stack[:level] if x]

            current = {
                "heading_level": level,
                "section_title": title,
                "section_path": section_path,
                "body_lines": [],
            }
        else:
            if current is None:
                current = {
                    "heading_level": 0,
                    "section_title": "",
                    "section_path": [],
                    "body_lines": [],
                }
            current["body_lines"].append(line)

    close_current()

    out: List[Dict[str, Any]] = []
    for sec in sections:
        title = sec.get("section_title", "").strip()
        body = sec.get("body", "").strip()
        if not title and not body:
            continue
        out.append(sec)

    return out


def _split_long_text(
    text: str,
    chunk_size: int = 800,
    overlap: int = 120,
) -> List[Dict[str, Any]]:
    text = _normalize_text(text)
    if not text:
        return []

    if len(text) <= chunk_size:
        return [{"start": 0, "end": len(text), "text": text}]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[Dict[str, Any]] = []
    buf = ""
    buf_start = 0
    cursor = 0

    def flush_buf() -> None:
        nonlocal buf, buf_start
        if buf.strip():
            chunks.append({
                "start": buf_start,
                "end": buf_start + len(buf),
                "text": buf.strip(),
            })
        buf = ""

    for p in paragraphs:
        p_start = text.find(p, cursor)
        if p_start < 0:
            p_start = cursor
        p_end = p_start + len(p)
        cursor = p_end

        if len(p) > chunk_size:
            flush_buf()

            step = max(1, chunk_size - overlap)
            i = 0
            while i < len(p):
                piece = p[i:i + chunk_size].strip()
                if piece:
                    chunks.append({
                        "start": p_start + i,
                        "end": min(p_start + i + chunk_size, p_end),
                        "text": piece,
                    })
                if i + chunk_size >= len(p):
                    break
                i += step
            continue

        candidate = p if not buf else f"{buf}\n\n{p}"
        if len(candidate) <= chunk_size:
            if not buf:
                buf_start = p_start
            buf = candidate
        else:
            flush_buf()
            buf = p
            buf_start = p_start

    flush_buf()
    return chunks


def _is_valid_chunk(
    *,
    section_title: str,
    body: str,
    heading_level: int,
) -> bool:
    text = _normalize_text(body)
    title = _normalize_text(section_title)

    if not text:
        return False

    if heading_level == 1:
        if text == title or len(text) <= len(title) + 5:
            return False

    if len(text) < 20:
        return False

    return True


def _make_embedding_text(
    filename: str,
    section_title: str,
    section_path: List[str],
    body: str,
    doc_role: Optional[str] = None,
    created_date: Optional[str] = None,
    section_date: Optional[str] = None,
    people: Optional[List[str]] = None,
    action_items: Optional[List[str]] = None,
) -> str:
    parts: List[str] = []

    if filename:
        parts.append(f"文件名: {filename}")

    if doc_role:
        parts.append(f"文档角色: {doc_role}")

    if created_date:
        parts.append(f"文件日期: {created_date}")

    if section_date:
        parts.append(f"章节日期: {section_date}")

    if section_title:
        parts.append(f"标题: {section_title}")

    if section_path:
        parts.append(f"路径: {' > '.join(section_path)}")

    if people:
        parts.append(f"相关人员: {', '.join(people)}")

    if action_items:
        parts.append("行动项:\n" + "\n".join(action_items))

    if body:
        parts.append(body.strip())

    return "\n\n".join(parts).strip()


def build_chunks_for_text(
    *,
    file_id: str,
    filename: str,
    text: str,
    chunk_size: int = 800,
    overlap: int = 120,
    file_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    text = _normalize_text(text)
    if not text:
        return []

    rows: List[Dict[str, Any]] = []
    idx = 1

    file_meta = file_meta or {}

    file_domain = file_meta.get("domain", "general")
    file_type = file_meta.get("file_type")
    project_name = file_meta.get("project_name")
    milestone = file_meta.get("milestone")
    version_tag = file_meta.get("version_tag")
    created_at = file_meta.get("created_at")
    created_at_iso = file_meta.get("created_at_iso") or _to_iso_datetime(created_at)
    created_date = file_meta.get("created_date") or _to_date_str(created_at)

    def push_chunk(
        *,
        body: str,
        start: int,
        end: int,
        section_title: str = "",
        heading_level: int = 0,
        section_path: Optional[List[str]] = None,
    ) -> None:
        nonlocal idx
        body = _normalize_text(body)
        if not body:
            return

        if not _is_valid_chunk(
            section_title=section_title,
            body=body,
            heading_level=heading_level,
        ):
            return

        chunk_id = f"{file_id}_{idx:04d}"
        path = section_path or []

        section_date = (
            _extract_date_from_text(section_title)
            or _extract_date_from_text(" > ".join(path))
            or _extract_date_from_text(body[:300])
        )

        doc_role = _infer_doc_role(
            filename=filename,
            section_title=section_title,
            section_path=path,
            body=body,
            file_meta=file_meta,
        )

        people = _extract_people(body)
        action_items = _extract_action_items(body)
        due_dates = _extract_due_dates(body)

        rows.append({
            "chunk_id": chunk_id,
            "chunk_index": idx,
            "start": start,
            "end": end,
            "text": body,
            "embedding_text": _make_embedding_text(
                filename=filename,
                section_title=section_title,
                section_path=path,
                body=body,
                doc_role=doc_role,
                created_date=created_date,
                section_date=section_date,
                people=people,
                action_items=action_items,
            ),
            "section_title": section_title,
            "heading_level": heading_level,
            "section_path": path,

            "filename": filename,
            "domain": file_domain,
            "file_type": file_type,
            "doc_role": doc_role,
            "project_name": project_name,
            "milestone": milestone,
            "version_tag": version_tag,

            "created_at": created_at,
            "created_at_iso": created_at_iso,
            "created_date": created_date,

            "section_date": section_date,
            "people": people,
            "action_items": action_items,
            "due_dates": due_dates,
        })
        idx += 1

    if _is_markdown(filename):
        sections = _split_markdown_sections(text)

        for sec in sections:
            title = sec.get("section_title", "")
            level = sec.get("heading_level", 0)
            path = sec.get("section_path", [])
            body = sec.get("body", "")

            section_text = body.strip()
            if title:
                section_text = f"{title}\n\n{section_text}".strip()

            sub_chunks = _split_long_text(
                text=section_text,
                chunk_size=chunk_size,
                overlap=overlap,
            )

            for sub in sub_chunks:
                push_chunk(
                    body=sub["text"],
                    start=sub["start"],
                    end=sub["end"],
                    section_title=title,
                    heading_level=level,
                    section_path=path,
                )
    else:
        sub_chunks = _split_long_text(
            text=text,
            chunk_size=chunk_size,
            overlap=overlap,
        )
        for sub in sub_chunks:
            push_chunk(
                body=sub["text"],
                start=sub["start"],
                end=sub["end"],
            )

    return rows