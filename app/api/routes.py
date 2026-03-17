# routes.py
from __future__ import annotations
from fastapi import APIRouter
from app.core.models import TaskRequest
from app.core.runtime import get_orchestrator, get_audit, get_store
from app.core.runtime import get_registry, get_policy
from fastapi import UploadFile, File, HTTPException
from app.core.runtime import get_file_service

router = APIRouter()


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

    specs = reg.list_specs()   # name -> ToolSpec
    names = reg.list_names()   # 包含没有 spec 的工具（比如你手动 register 的 builtins）

    out = []
    for name in names:
        spec = specs.get(name)
        out.append({
            "name": name,
            "allowed": (name in pol.allow_tools),
            "risk": getattr(spec, "risk", "unknown"),
            "description": getattr(spec, "description", ""),
        })
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

