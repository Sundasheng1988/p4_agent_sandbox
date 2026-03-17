from __future__ import annotations

from typing import Any, Dict, List


def build_context(hits: List[Dict[str, Any]], max_chars: int = 4000) -> str:
    """
    将 semantic retrieval 返回的 hits 拼接为上下文。
    控制总字符数，避免 prompt 过长。
    """
    parts: List[str] = []
    total = 0

    for i, hit in enumerate(hits, start=1):
        snippet = (hit.get("snippet") or "").strip()
        filename = hit.get("filename", "")
        chunk_id = hit.get("chunk_id", "")
        score = hit.get("score", 0)

        if not snippet:
            continue

        block = (
            f"[{i}] "
            f"file={filename} "
            f"chunk={chunk_id} "
            f"score={score}\n"
            f"{snippet}"
        )

        if total + len(block) > max_chars:
            break

        parts.append(block)
        total += len(block) + 2

    return "\n\n".join(parts)