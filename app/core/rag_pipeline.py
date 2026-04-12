#rag_pipeline
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from app.core.embeddings import embed_query, cosine_score
from app.core.llm_client import generate_with_ollama
from app.core.hybrid_retrieval import hybrid_retrieve
from app.core.context_builder import build_context


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
    chunk_path = sandbox / "artifacts" / "chunks" / f"{file_id}.chunks.json"
    if not chunk_path.exists():
        return {}
    return _load_json(chunk_path)


def _get_full_chunk_text(sandbox: Path, file_id: str, chunk_id: str) -> str:
    rec = _load_chunk_record(sandbox, file_id=file_id)
    chunks = rec.get("chunks", []) or []

    for c in chunks:
        if c.get("chunk_id") == chunk_id:
            return (c.get("text") or "").strip()

    return ""


def _normalize_extra_context(extra_context: Any) -> str:
    if extra_context is None:
        return ""

    if isinstance(extra_context, str):
        return extra_context.strip()

    if isinstance(extra_context, (list, dict)):
        try:
            return json.dumps(extra_context, ensure_ascii=False, indent=2).strip()
        except Exception:
            return str(extra_context).strip()

    return str(extra_context).strip()


def _load_file_meta(sandbox_root: Path, file_id: str) -> Dict[str, Any]:
    meta_path = sandbox_root / "uploads" / file_id / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        return _load_json(meta_path)
    except Exception:
        return {}


def _match_filters(
    *,
    file_meta: Dict[str, Any],
    domain: str | None,
    file_type: str | None,
    source: str | None,
) -> bool:
    if domain and file_meta.get("domain") != domain:
        return False
    if file_type and file_meta.get("file_type") != file_type:
        return False
    if source and file_meta.get("source") != source:
        return False
    return True


def semantic_retrieve(
    sandbox_root: str,
    question: str,
    top_k: int = 10,
    domain: str | None = None,
    file_type: str | None = None,
    source: str | None = None,
) -> Dict[str, Any]:
    sandbox = Path(sandbox_root)
    vector_index_path = sandbox / "artifacts" / "vector_index.json"

    if not vector_index_path.exists():
        return {
            "ok": False,
            "hits": [],
            "reason": "vector_index.json not found",
        }

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
    filtered_file_count = 0

    for item in items:
        file_id = item.get("file_id", "")
        filename = item.get("filename", "")
        manifest_rel = item.get("record_path")
        if not manifest_rel:
            continue

        file_meta = {
            "domain": item.get("domain"),
            "file_type": item.get("file_type"),
            "source": item.get("source"),
        }

        if not any(file_meta.values()):
            full_meta = _load_file_meta(sandbox_root=sandbox, file_id=file_id)
            file_meta = {
                "domain": full_meta.get("domain"),
                "file_type": full_meta.get("file_type"),
                "source": full_meta.get("source"),
            }

        if not _match_filters(
            file_meta=file_meta,
            domain=domain,
            file_type=file_type,
            source=source,
        ):
            continue

        filtered_file_count += 1

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
                "domain": file_meta.get("domain"),
                "file_type": file_meta.get("file_type"),
                "source": file_meta.get("source"),
            }
            hits.append((score, hit))

    hits.sort(key=lambda x: x[0], reverse=True)
    top_hits = [h for _, h in hits[:top_k]]

    return {
        "ok": True,
        "query": question,
        "domain": domain,
        "file_type": file_type,
        "source": source,
        "hits": top_hits,
        "hits_total": len(hits),
        "filtered_file_count": filtered_file_count,
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
    ctx,
    sandbox_root: str,
    question: str,
    model_name: str,
    top_k: int = 10,
    max_context_chars: int = 4000,
    extra_context: Any = None,
    domain: str | None = None,
    file_type: str | None = None,
    source: str | None = None,
) -> Dict[str, Any]:
    retrieval_out = await hybrid_retrieve(
        ctx,
        query=question,
        limit=top_k,
        domain=domain,
        file_type=file_type,
        source=source,
    )

    if not retrieval_out.get("ok", False):
        return {
            "question": question,
            "domain": domain,
            "file_type": file_type,
            "source": source,
            "hits": [],
            "context": "",
            "prompt": "",
            "answer": "",
            "llm_model": model_name,
            "done": False,
            "error": retrieval_out.get("reason", "hybrid retrieval failed"),
        }

    hits = retrieval_out.get("hits", []) or []
    context = build_context(
        hits=hits,
        max_chars=max_context_chars,
        query=question,
    )

    extra_context_text = _normalize_extra_context(extra_context)
    final_context = context

    if extra_context_text:
        final_context = (
            f"{context}\n\n"
            f"[Planner Extra Context]\n"
            f"{extra_context_text}"
        ).strip()

    prompt = build_rag_prompt(question=question, context=final_context)

    llm_out = generate_with_ollama(
        prompt=prompt,
        model_name=model_name,
        timeout=120,
    )

    answer = (llm_out.get("response") or "").strip()

    return {
        "question": question,
        "domain": domain,
        "file_type": file_type,
        "source": source,
        "hits": hits,
        "context": final_context,
        "prompt": prompt,
        "answer": answer,
        "llm_model": llm_out.get("model", model_name),
        "done": llm_out.get("done", True),
        "error": None,
    }