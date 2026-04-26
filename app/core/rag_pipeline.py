#rag_pipeline
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

from app.core.embeddings import embed_query, cosine_score
from app.core.llm_client import generate_with_ollama
from app.core.hybrid_retrieval import hybrid_retrieve, hybrid_retrieve_multi_query
from app.core.context_builder import build_context

from app.core.query_understanding import analyze_query
from app.core.router import build_retrieval_config


SYSTEM_PROMPT = """你是一个严格基于知识库的问答助手（Grounded QA Assistant）。

必须遵守以下规则：

【核心原则】
1. 所有回答必须完全基于提供的“知识库上下文”
2. 不允许使用常识补充、推测或自行总结未出现的信息
3. 如果上下文没有明确说明，必须回答：
   “未在知识库中找到明确答案”

【排序 / 判断类问题】
4. 如果用户问：
   - 最大 / 最重要 / 最优先 / 第一 / 核心问题
   但上下文没有明确排序或结论

   必须回答：
   “材料中未明确说明”

   然后列出上下文中的所有相关项。

【相关项抽取规则】
5. 当上下文中出现以下字段或表达时，必须优先抽取为相关项：
   - 当前发现
   - 当前问题
   - 但存在问题
   - 但：
   - 问题逐渐明显
   - 未完成
   - 仍为空
   - 无法
   - 不稳定
   - 不足
   - 缺失
   - 未进入
   - 未使用
   - 补全行为

6. 如果用户问“问题是什么 / 核心问题是什么 / 当前问题是什么”，即使材料没有明确写“最大问题”，也要把“当前发现 / 但 / 问题 / 无法 / 不稳定 / 缺失”下面的条目列为相关问题。

【表达要求】
7. 必须使用中文回答
8. 优先直接回答问题
9. 内容简洁清晰
10. 不允许编造或扩展信息
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
    domains: list[str] | None,
    file_type: str | None,
    source: str | None,
) -> bool:
    if domains and file_meta.get("domain") not in domains:
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
    domains: list[str] | None = None,
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
            domains=domains,
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
        "domains": domains,
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
    domains: list[str] | None = None,
    file_type: str | None = None,
    source: str | None = None,
) -> Dict[str, Any]:
    # =========================================================
    # 1) Query Understanding
    # =========================================================
    q = analyze_query(question)

    # =========================================================
    # 2) Router
    # 优先使用 query_understanding 结果
    # 如果调用方显式传入 domains / file_type / source，则仍允许覆盖
    # =========================================================
    retrieval_config = build_retrieval_config(q)

    effective_domains = domains if domains is not None else retrieval_config.get("domains")
    effective_file_type = file_type if file_type is not None else retrieval_config.get("file_type")
    effective_source = source if source is not None else retrieval_config.get("source")
    retrieval_mode = retrieval_config.get("mode", "hybrid")
    retrieval_queries = retrieval_config.get("queries") or [question]
    effective_filename = retrieval_config.get("filename")
    effective_doc_role = retrieval_config.get("doc_role")
    effective_section_title = retrieval_config.get("section_title")
    effective_section_date = retrieval_config.get("section_date")

    # =========================================================
    # 3) Retrieval
    # M4.8.13 Multi-query Retrieval v1
    # =========================================================
    max_multi_queries = 4
    effective_queries = retrieval_queries[:max_multi_queries] if retrieval_queries else [question]

    if len(effective_queries) == 1:
        effective_query = effective_queries[0]
        retrieval_out = await hybrid_retrieve(
            ctx,
            query=effective_query,
            limit=top_k,
            domains=effective_domains,
            file_type=effective_file_type,
            source=effective_source,
            filename=effective_filename,
            doc_role=effective_doc_role,
            section_title=effective_section_title,
            section_date=effective_section_date,
        )
    else:
        effective_query = effective_queries[0]
        retrieval_out = await hybrid_retrieve_multi_query(
            ctx,
            queries=effective_queries,
            limit=top_k,
            domains=effective_domains,
            file_type=effective_file_type,
            source=effective_source,
            per_query_limit=max(top_k * 2, 10),
            filename=effective_filename,
            doc_role=effective_doc_role,
            section_title=effective_section_title,
            section_date=effective_section_date,
        )

    if not retrieval_out.get("ok", False):
        return {
            "question": question,
            "original_query": q.original_query,
            "rewritten_query": q.rewritten_query,
            "retrieval_queries": retrieval_queries,
            "query_type": q.query_type,
            "target_domains": effective_domains,
            "retrieval_mode": retrieval_mode,
            "routing_reason": retrieval_config.get("routing_reason"),
            "router_notes": retrieval_config.get("notes", []),
            "domains": effective_domains,
            "file_type": effective_file_type,
            "source": effective_source,
            "hits": [],
            "context": "",
            "prompt": "",
            "answer": "",
            "llm_model": model_name,
            "done": False,
            "error": retrieval_out.get("reason", "hybrid retrieval failed"),

            "filename": effective_filename,
            "doc_role": effective_doc_role,
            "section_title": effective_section_title,
            "section_date": effective_section_date,
        }

    hits = retrieval_out.get("hits", []) or []

    # =========================================================
    # 4) Context Builder
    # =========================================================
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

    # =========================================================
    # 5) Prompt + LLM
    # =========================================================
    prompt = build_rag_prompt(question=question, context=final_context)

    llm_out = generate_with_ollama(
        prompt=prompt,
        model_name=model_name,
        timeout=120,
    )

    answer = (llm_out.get("response") or "").strip()

    # =========================================================
    # 6) Debug Fields
    # 这里是 Week 1 的关键交付
    # =========================================================
    return {
        "question": question,
        "original_query": q.original_query,
        "rewritten_query": q.rewritten_query,
        "retrieval_queries": retrieval_queries,
        "query_type": q.query_type,
        "target_domains": effective_domains,
        "retrieval_mode": retrieval_mode,
        "routing_reason": retrieval_config.get("routing_reason"),
        "router_notes": retrieval_config.get("notes", []),
        "domains": effective_domains,
        "file_type": effective_file_type,
        "source": effective_source,
        "effective_query": effective_query,
        "effective_queries": effective_queries,
        "retrieval_search_mode": retrieval_out.get("search_mode"),
        "hits": hits,
        "context": final_context,
        "prompt": prompt,
        "answer": answer,
        "llm_model": llm_out.get("model", model_name),
        "done": llm_out.get("done", True),
        "error": None,

        "filename": effective_filename,
        "doc_role": effective_doc_role,
        "section_title": effective_section_title,
        "section_date": effective_section_date,
    }