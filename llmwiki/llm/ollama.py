"""사내 Ollama 공급자 (망분리 환경용)."""

from __future__ import annotations

from typing import Any

import httpx


class OllamaProvider:
    name = "ollama"

    def __init__(self, options: dict[str, Any]) -> None:
        self.base_url = options.get("base_url", "http://localhost:11434").rstrip("/")
        self.model = options.get("model", "qwen2.5-coder:32b")
        self.num_ctx = int(options.get("num_ctx", 32768))
        # keep_alive 를 짧게 두면 호출마다 모델을 다시 적재해 극단적으로 느려진다.
        self.keep_alive = options.get("keep_alive", "30m")
        self.timeout = float(options.get("timeout", 900))

    def complete(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"num_ctx": self.num_ctx},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return (data.get("message", {}).get("content") or "").strip()
