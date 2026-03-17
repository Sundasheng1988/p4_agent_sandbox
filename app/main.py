from __future__ import annotations
from fastapi import FastAPI
from app.api.routes import router
from app.core.runtime import startup

app = FastAPI(title="P4 Agent Runtime (Epic A)", version="0.1")
app.include_router(router)


@app.on_event("startup")
async def _startup():
    await startup()
