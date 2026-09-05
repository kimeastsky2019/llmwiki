"""사내 Ollama 공급자 (망분리 환경용)."""

from __future__ import annotations

from typing import Any

import httpx


class OllamaProvider:
    name = "ollama"

    def __init__(self, options: dict[str, Any]) -> None:
        self.base_url = options.get("base_url", "http://localhost:11434").rstrip("/")
        self.model = options.get("model", "qwen2.5-coder:32b")
        # ★ num_ctx 는 성능에 직결된다. 가중치 + KV 캐시가 VRAM 을 넘으면
        #   ollama 가 일부를 CPU 로 내리고 처리량이 5배 넘게 떨어진다.
        #   A30 24GB + qwen3:32b(Q4, 20GB) 실측 —
        #     num_ctx 32768 → 18% CPU/82% GPU ·  4.3 tok/s
        #     num_ctx  8192 → 100% GPU        · 23.7 tok/s
        #   컨텍스트를 늘리기 전에 `ollama ps` 의 PROCESSOR 열을 볼 것.
        self.num_ctx = int(options.get("num_ctx", 8192))
        # 답변 길이 상한. 없으면 모델이 멈출 때까지 쓰고, 화면은 그동안 기다린다.
        self.num_predict = int(options.get("num_predict", 0))
        # keep_alive 를 짧게 두면 호출마다 모델을 다시 적재해 극단적으로 느려진다.
        self.keep_alive = options.get("keep_alive", "30m")
        self.timeout = float(options.get("timeout", 900))

    def complete(self, system: str, prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "num_ctx": self.num_ctx,
                **({"num_predict": self.num_predict} if self.num_predict > 0 else {}),
            },
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
