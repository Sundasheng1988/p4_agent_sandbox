from __future__ import annotations

import json
from typing import Any, Dict
from urllib import request, error


DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


def generate_with_ollama(
    prompt: str,
    model_name: str,
    timeout: int = 120,
) -> Dict[str, Any]:
    """
    调用本地 Ollama /api/generate
    返回：
    {
        "model": ...,
        "response": ...,
        "done": true/false,
        ...
    }
    """
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        DEFAULT_OLLAMA_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Ollama HTTPError {e.code}: {detail}") from e
    except Exception as e:
        raise RuntimeError(f"Ollama request failed: {e}") from e