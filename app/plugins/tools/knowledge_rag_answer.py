from __future__ import annotations

from typing import Any, Dict

from app.core.rag_pipeline import run_rag_pipeline
from app.tools.spec import ToolSpec


async def _handler(ctx, args: Dict[str, Any]) -> Dict[str, Any]:
    args = args or {}

    question = str(args.get("question", "")).strip()
    top_k = int(args.get("top_k", 5))
    max_context_chars = int(args.get("max_context_chars", 4000))
    model_name = str(args.get("model_name", "")).strip()

    if not question:
        raise ValueError("question is required")
    if top_k < 1 or top_k > 20:
        raise ValueError("top_k must be 1..20")
    if max_context_chars < 500 or max_context_chars > 20000:
        raise ValueError("max_context_chars must be 500..20000")
    if not model_name:
        raise ValueError("model_name is required")

    rag_out = await run_rag_pipeline(
        sandbox_root=ctx.sandbox_root,
        question=question,
        model_name=model_name,
        top_k=top_k,
        max_context_chars=max_context_chars,
    )

    return {
        "ok": rag_out.get("error") is None,
        "question": question,
        "top_k": top_k,
        "model_name": model_name,
        "llm_model": rag_out.get("llm_model", model_name),
        "hits": [
            {
                "file_id": h.get("file_id"),
                "filename": h.get("filename"),
                "chunk_id": h.get("chunk_id"),
                "chunk_index": h.get("chunk_index"),
                "score": h.get("score"),
                "snippet": h.get("snippet"),
            }
            for h in rag_out.get("hits", [])
        ],
        "context_preview": rag_out.get("context", "")[:800],
        "full_context": rag_out.get("context", ""),
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
        },
        "required": ["question", "model_name"],
    },
)