# knowledge_rag_answer
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.core.rag_pipeline import run_rag_pipeline
from app.tools.spec import ToolSpec


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


def _normalize_domains(domains: Any) -> Optional[List[str]]:
    if domains is None:
        return None

    if isinstance(domains, str):
        domains = [domains]

    if isinstance(domains, list):
        clean = [str(d).strip() for d in domains if str(d).strip()]
        return clean or None

    return None


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}

    question = str(args.get("question", "")).strip()
    top_k = int(args.get("top_k", 5))
    max_context_chars = int(args.get("max_context_chars", 4000))
    model_name = str(args.get("model_name", "")).strip()
    extra_context = args.get("extra_context")

    # ✅ multi-domain
    domains = _normalize_domains(args.get("domains"))

    file_type = args.get("file_type")
    source = args.get("source")

    if file_type is not None:
        file_type = str(file_type).strip() or None
    if source is not None:
        source = str(source).strip() or None

    if not question:
        raise ValueError("question is required")
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be 1..20")
    if max_context_chars < 500 or max_context_chars > 20000:
        raise ValueError("max_context_chars must be 500..20000")
    if not model_name:
        raise ValueError("model_name is required")

    extra_context_text = _normalize_extra_context(extra_context)

    # ✅ 核心：传 domains
    rag_out = await run_rag_pipeline(
        ctx=ctx,
        sandbox_root=ctx.sandbox_root,
        question=question,
        model_name=model_name,
        top_k=top_k,
        max_context_chars=max_context_chars,
        extra_context=extra_context_text,
        domains=domains,   # ← 关键修改
        file_type=file_type,
        source=source,
    )

    full_context = rag_out.get("context", "") or ""

    return {
        "ok": rag_out.get("error") is None,
        "question": question,
        "top_k": top_k,
        "model_name": model_name,

        # ✅ 返回 domains
        "domains": domains,
        "file_type": file_type,
        "source": source,

        "llm_model": rag_out.get("llm_model", model_name),

        "hits": [
            {
                "file_id": h.get("file_id"),
                "filename": h.get("filename"),
                "chunk_id": h.get("chunk_id"),
                "chunk_index": h.get("chunk_index"),
                "score": h.get("score"),
                "snippet": h.get("snippet"),
                "domain": h.get("domain"),
                "file_type": h.get("file_type"),
                "source": h.get("source"),
            }
            for h in rag_out.get("hits", [])
        ],

        "extra_context_used": bool(extra_context_text),
        "extra_context_preview": extra_context_text[:800],
        "context_preview": full_context[:800],
        "full_context": full_context,
        "prompt_preview": rag_out.get("prompt", "")[:2000],
        "answer": rag_out.get("answer", ""),
        "done": rag_out.get("done", True),
        "error": rag_out.get("error"),
    }


TOOL = ToolSpec(
    name="knowledge_rag_answer",
    handler=_handler,
    risk="medium",
    description="Answer a question using semantic retrieval + local Ollama/Qwen generation.",
    args_schema={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 20},
            "max_context_chars": {"type": "integer", "minimum": 500, "maximum": 20000},
            "model_name": {"type": "string"},
            "extra_context": {},

            # ✅ 新增 multi-domain
            "domains": {
                "type": ["array", "null"],
                "items": {"type": "string"}
            },

            "file_type": {"type": ["string", "null"]},
            "source": {"type": ["string", "null"]},
        },
        "required": ["question", "model_name"],
    },
)