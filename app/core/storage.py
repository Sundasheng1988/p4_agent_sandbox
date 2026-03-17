from __future__ import annotations

import aiosqlite
import os
import time
from typing import Optional, Dict, Any, List

DB_PATH = os.path.expanduser("~/p4_agent_sandbox/db/app.db")


class TaskStore:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = os.path.expanduser(db_path)

    async def init(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            # tasks
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    trace_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    error TEXT
                )
                """
            )

            # files (C1-1)
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    file_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    mime TEXT NOT NULL,
                    ext TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    rel_dir TEXT NOT NULL,
                    raw_name TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )

            await db.commit()

    async def create_task(self, trace_id: str, user_input: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO tasks(trace_id,status,user_input,started_at) VALUES(?,?,?,?)",
                (trace_id, "planning", user_input, time.time()),
            )
            await db.commit()

    async def update_task(
        self, trace_id: str, status: str, error: Optional[str] = None, ended: bool = False
    ):
        async with aiosqlite.connect(self.db_path) as db:
            if ended:
                await db.execute(
                    "UPDATE tasks SET status=?, ended_at=?, error=? WHERE trace_id=?",
                    (status, time.time(), error, trace_id),
                )
            else:
                await db.execute(
                    "UPDATE tasks SET status=?, error=? WHERE trace_id=?",
                    (status, error, trace_id),
                )
            await db.commit()

    async def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM tasks ORDER BY started_at DESC LIMIT ?",
                (int(limit),),
            )
            rows = await cur.fetchall()
            await cur.close()
            return [dict(r) for r in rows]

    # ---------------- C1-1: files ----------------

    async def upsert_file(self, rec: Dict[str, Any]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO files
                (file_id, filename, mime, ext, size, sha256, rel_dir, raw_name, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec["file_id"],
                    rec["filename"],
                    rec["mime"],
                    rec["ext"],
                    int(rec["size"]),
                    rec["sha256"],
                    rec["rel_dir"],
                    rec["raw_name"],
                    float(rec["created_at"]),
                ),
            )
            await db.commit()

    async def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT file_id, filename, mime, ext, size, sha256, rel_dir, raw_name, created_at
                FROM files WHERE file_id = ?
                """,
                (file_id,),
            )
            row = await cur.fetchone()
            await cur.close()
            if not row:
                return None
            keys = ["file_id","filename","mime","ext","size","sha256","rel_dir","raw_name","created_at"]
            return dict(zip(keys, row))

    async def list_files(self, limit: int = 50) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                """
                SELECT file_id, filename, mime, ext, size, sha256, rel_dir, raw_name, created_at
                FROM files ORDER BY created_at DESC LIMIT ?
                """,
                (int(limit),),
            )
            rows = await cur.fetchall()
            await cur.close()
            keys = ["file_id","filename","mime","ext","size","sha256","rel_dir","raw_name","created_at"]
            return [dict(zip(keys, r)) for r in rows]
