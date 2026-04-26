# routes.py
from __future__ import annotations

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.core.models import TaskRequest
from app.core.runtime import (
    get_orchestrator,
    get_audit,
    get_store,
    get_registry,
    get_policy,
    get_file_service,
)
from app.core.router import route_query
from app.core.agent_runtime import run_agent_runtime

router = APIRouter()


class AgentRuntimeRequest(BaseModel):
    user_input: str
    model_name: str = "qwen2.5:7b-instruct"
    top_k: int = 8
    max_context_chars: int = 5000


@router.get("/health")
def health():
    return {"ok": True}


@router.post("/task/run")
async def run_task(req: TaskRequest):
    orch = get_orchestrator()
    state = await orch.run(req)
    return orch.to_user_response(state, debug=req.debug)


@router.get("/trace/{trace_id}")
def trace(trace_id: str):
    audit = get_audit()
    return audit.read_all(trace_id)


@router.get("/tasks")
async def list_tasks(limit: int = 50):
    store = get_store()
    return await store.list_tasks(limit=limit)


@router.get("/tools")
def list_tools():
    reg = get_registry()
    pol = get_policy()

    specs = reg.list_specs()
    names = reg.list_names()

    out = []
    for name in names:
        spec = specs.get(name)
        out.append(
            {
                "name": name,
                "allowed": (name in pol.allow_tools),
                "risk": getattr(spec, "risk", "unknown"),
                "description": getattr(spec, "description", ""),
            }
        )
    return out


@router.post("/files/upload")
async def upload_file(file: UploadFile = File(...)):
    fs = get_file_service()
    data = await file.read()
    meta = await fs.save_upload(
        filename=file.filename,
        mime=(file.content_type or "application/octet-stream"),
        data=data,
    )
    return {"ok": True, "meta": meta}


@router.get("/files")
async def list_files(limit: int = 50):
    store = get_store()
    return await store.list_files(limit=limit)


@router.get("/files/{file_id}")
async def get_file_meta(file_id: str):
    store = get_store()
    rec = await store.get_file(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail="file not found")
    return rec


@router.get("/files/{file_id}/meta")
async def get_file_full_meta(file_id: str):
    fs = get_file_service()
    try:
        meta = await fs.get_meta_by_id(file_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="file meta not found")
    return meta


@router.get("/route/preview")
def preview_route(q: str):
    route = route_query(q)
    return {
        "query": q,
        "domains": route.domains,
        "primary_domain": route.primary_domain,
        "source": route.source,
        "file_type": route.file_type,
        "strategy": route.strategy,
        "notes": route.notes,
    }


@router.post("/agent/run")
async def run_agent(request: AgentRuntimeRequest):
    from app.core.runtime import get_ctx

    ctx = get_ctx()

    out = await run_agent_runtime(
        ctx=ctx,
        sandbox_root=str(ctx.sandbox_root),
        user_input=request.user_input,
        model_name=request.model_name,
        top_k=request.top_k,
        max_context_chars=request.max_context_chars,
    )
    return out