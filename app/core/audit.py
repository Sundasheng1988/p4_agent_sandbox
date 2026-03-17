from __future__ import annotations
import json
import os
import time
from typing import Any, Dict, List


class AuditLogger:
    """
    JSONL trace logger.
    One line = one event. Order matters.
    Path: ~/p4_agent_sandbox/logs/<trace_id>.jsonl
    """

    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def _path(self, trace_id: str) -> str:
        return os.path.join(self.log_dir, f"{trace_id}.jsonl")

    def write(self, trace_id: str, event: str, payload: Dict[str, Any]):
        rec = {
            "ts": time.time(),
            "trace_id": trace_id,
            "event": event,
            "payload": payload,
        }
        with open(self._path(trace_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def read_all(self, trace_id: str) -> List[Dict[str, Any]]:
        p = self._path(trace_id)
        if not os.path.exists(p):
            return []
        out: List[Dict[str, Any]] = []
        with open(p, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out
