# chunking.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _normalize_text(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _is_markdown(filename: str) -> bool:
    return (filename or "").lower().endswith(".md")


def _split_markdown_sections(text: str) -> List[Dict[str, Any]]:
    """
    按 Markdown 标题切 section。
    支持:
      # title
      ## title
      ### title
      #### title ...

    返回:
    [
      {
        "heading_level": 1|2|3...,
        "section_title": "...",
        "section_path": [...],
        "body": "..."
      },
      ...
    ]
    """
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
    """
    对超长文本做二次切块：
    1) 优先按段落聚合
    2) 如果单段过长，再按字符窗口切
    返回 [{"start": x, "end": y, "text": "..."}]
    """
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
    """
    过滤低价值 chunk：
    1. 纯标题空块
    2. 过短无信息块
    """
    text = _normalize_text(body)
    title = _normalize_text(section_title)

    if not text:
        return False

    # 1) 一级标题且正文基本只有标题本身
    if heading_level == 1:
        if text == title or len(text) <= len(title) + 5:
            return False

    # 2) 太短且信息量很低
    if len(text) < 20:
        return False

    return True

def _make_embedding_text(
    filename: str,
    section_title: str,
    section_path: List[str],
    body: str,
) -> str:
    parts: List[str] = []

    if filename:
        parts.append(f"文件名: {filename}")

    if section_title:
        parts.append(f"标题: {section_title}")

    if section_path:
        parts.append(f"路径: {' > '.join(section_path)}")

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
) -> List[Dict[str, Any]]:
    """
    统一 chunk builder:
    - Markdown: 标题优先切块
    - 非 Markdown: 固定长度回退

    返回 chunk rows:
    [
      {
        "chunk_id": "..._0001",
        "chunk_index": 1,
        "start": 0,
        "end": 123,
        "text": "...",
        "embedding_text": "...",
        "section_title": "...",
        "heading_level": 2,
        "section_path": [...]
      }
    ]
    """
    text = _normalize_text(text)
    if not text:
        return []

    rows: List[Dict[str, Any]] = []
    idx = 1

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
            ),
            "section_title": section_title,
            "heading_level": heading_level,
            "section_path": path,
        })
        idx += 1

    if _is_markdown(filename):
        sections = _split_markdown_sections(text)

        for sec in sections:
            title = sec.get("section_title", "")
            level = sec.get("heading_level", 0)
            path = sec.get("section_path", [])
            body = sec.get("body", "")

            # 标题本身加入正文，强化 section 语义
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