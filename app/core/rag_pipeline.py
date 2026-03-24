#rag_pipeline
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from app.core.embeddings import embed_query, cosine_score
from app.core.llm_client import generate_with_ollama


SYSTEM_PROMPT = """你是一个知识库问答助手。

请严格依据提供的知识库上下文回答问题，不要脱离上下文自由发挥。
如果上下文信息不足，请明确回答：“未在知识库中找到明确答案”。

回答要求：
1. 必须使用中文回答
2. 如果英文术语已有常见中文含义，请直接翻译成中文
3. 不要输出中英混杂词，例如“腰coat pocket”这类表达
4. 回答尽量简洁、清晰
5. 优先直接回答问题
6. 不要编造不存在的信息
"""


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_chunk_record(sandbox: Path, file_id: str) -> Dict[str, Any]:
    """
    读取单个文件的 chunks 记录
    artifacts/chunks/<file_id>.chunks.json
    """
    chunk_path = sandbox / "artifacts" / "chunks" / f"{file_id}.chunks.json"
    if not chunk_path.exists():
        return {}
    return _load_json(chunk_path)


def _get_full_chunk_text(sandbox: Path, file_id: str, chunk_id: str) -> str:
    """
    根据 file_id + chunk_id 从 chunks.json 中取完整 chunk 文本
    """
    rec = _load_chunk_record(sandbox, file_id=file_id)
    chunks = rec.get("chunks", []) or []

    for c in chunks:
        if c.get("chunk_id") == chunk_id:
            return (c.get("text") or "").strip()

    return ""


def build_context_from_hits(hits: List[Dict[str, Any]], max_chars: int = 4000) -> str:
    """
    使用完整 chunk 文本构造上下文，而不是 snippet。
    """
    parts: List[str] = []
    total = 0

    for i, hit in enumerate(hits, start=1):
        text = (hit.get("full_text") or hit.get("snippet") or "").strip()
        if not text:
            continue

        filename = hit.get("filename", "")
        chunk_id = hit.get("chunk_id", "")
        score = hit.get("score", 0)

        block = (
            f"[{i}] "
            f"file={filename} "
            f"chunk={chunk_id} "
            f"score={score}\n"
            f"{text}"
        )

        if total + len(block) > max_chars:
            break

        parts.append(block)
        total += len(block) + 2

    return "\n\n".join(parts)


def semantic_retrieve(
    sandbox_root: str,
    question: str,
    top_k: int = 5,
) -> Dict[str, Any]:
    sandbox = Path(sandbox_root)
    vector_index_path = sandbox / "artifacts" / "vector_index.json"

    if not vector_index_path.exists():
        return {"ok": False, "hits": [], "reason": "vector_index.json not found"}

    vector_index = _load_json(vector_index_path)
    model_name = str(vector_index.get("model_name", "all-MiniLM-L6-v2")).strip()
    normalize = bool(vector_index.get("normalize", True))
    items = vector_index.get("items", [])

    query_vec = embed_query(
        query=question,
        model_name=model_name,
        normalize=normalize,
    )

    hits: List[Tuple[float, Dict[str, Any]]] = []

    for item in items:
        file_id = item.get("file_id", "")
        filename = item.get("filename", "")
        manifest_rel = item.get("record_path")
        if not manifest_rel:
            continue

        manifest_path = sandbox / manifest_rel
        if not manifest_path.exists():
            continue

        manifest = _load_json(manifest_path)

        for row in manifest.get("vectors", []):
            vector_rel = row.get("vector_path")
            if not vector_rel:
                continue

            vector_path = sandbox / vector_rel
            if not vector_path.exists():
                continue

            doc_vec = np.load(vector_path).astype(np.float32)
            score = cosine_score(query_vec, doc_vec)

            chunk_id = row.get("chunk_id")
            snippet = (row.get("text_preview") or "").strip()
            full_text = _get_full_chunk_text(
                sandbox=sandbox,
                file_id=file_id,
                chunk_id=chunk_id,
            )

            hit = {
                "file_id": file_id,
                "filename": filename,
                "chunk_id": chunk_id,
                "chunk_index": row.get("chunk_index"),
                "score": round(float(score), 6),
                "snippet": snippet,
                "full_text": full_text,
                "start": row.get("start"),
                "end": row.get("end"),
                "search_mode": "semantic",
            }
            hits.append((score, hit))

    hits.sort(key=lambda x: x[0], reverse=True)
    top_hits = [h for _, h in hits[:top_k]]

    return {
        "ok": True,
        "query": question,
        "hits": top_hits,
        "hits_total": len(hits),
        "model_name": model_name,
    }


def build_rag_prompt(question: str, context: str) -> str:
    return f"""{SYSTEM_PROMPT}

知识库上下文：
{context}

用户问题：
{question}

请用中文作答：
"""


async def run_rag_pipeline(
    sandbox_root: str,
    question: str,
    model_name: str,
    top_k: int = 5,
    max_context_chars: int = 4000,
) -> Dict[str, Any]:
    semantic_out = semantic_retrieve(
        sandbox_root=sandbox_root,
        question=question,
        top_k=top_k,
    )

    if not semantic_out.get("ok", False):
        return {
            "question": question,
            "hits": [],
            "context": "",
            "prompt": "",
            "answer": "",
            "llm_model": model_name,
            "done": False,
            "error": semantic_out.get("reason", "semantic retrieval failed"),
        }

    hits = semantic_out.get("hits", []) or []
    context = build_context_from_hits(hits=hits, max_chars=max_context_chars)
    prompt = build_rag_prompt(question=question, context=context)

    llm_out = generate_with_ollama(
        prompt=prompt,
        model_name=model_name,
        timeout=120,
    )

    answer = (llm_out.get("response") or "").strip()

    return {
        "question": question,
        "hits": hits,
        "context": context,
        "prompt": prompt,
        "answer": answer,
        "llm_model": llm_out.get("model", model_name),
        "done": llm_out.get("done", True),
        "error": None,
    }