from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import os
import yaml


@dataclass
class AppConfig:
    sandbox_root: str
    log_dir: str
    db_path: str


@dataclass
class PolicyConfig:
    allow_tools: List[str]


@dataclass
class ServerConfig:
    host: str
    port: int


@dataclass
class Config:
    app: AppConfig
    policy: PolicyConfig
    server: ServerConfig


def load_config(path: str = "config.yaml") -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(f"config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    app = data.get("app", {})
    policy = data.get("policy", {})
    server = data.get("server", {})

    cfg = Config(
        app=AppConfig(
            sandbox_root=str(app.get("sandbox_root", os.path.expanduser("~/p4_agent_sandbox"))),
            log_dir=str(app.get("log_dir", os.path.expanduser("~/p4_agent_sandbox/logs"))),
            db_path=str(app.get("db_path", os.path.expanduser("~/p4_agent_sandbox/db/app.db"))),
        ),
        policy=PolicyConfig(
            allow_tools=list(policy.get("allow_tools", []))
        ),
        server=ServerConfig(
            host=str(server.get("host", "127.0.0.1")),
            port=int(server.get("port", 8000)),
        ),
    )
    return cfg
