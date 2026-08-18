"""xAI Grok 공급자.

xAI 는 OpenAI 호환 스펙을 그대로 따른다 (POST /v1/chat/completions).
그래서 SDK 없이 httpx 만으로 충분하다 — 사내 서버에 의존성을 하나라도
덜 얹는 편이 배포가 쉽다.

키는 XAI_API_KEY 환경변수에서 읽는다. config.yaml 에는 절대 적지 않는다.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-4.20-0309-non-reasoning"


class GrokProvider:
    name = "grok"

    def __init__(self, options: dict[str, Any]) -> None:
        self.base_url = str(
            options.get("base_url") or os.environ.get("XAI_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = options.get("model") or os.environ.get("XAI_MODEL") or DEFAULT_MODEL
        self.max_tokens = int(options.get("max_tokens", 16000))
        self.temperature = float(options.get("temperature", 0.2))
        # 명세서 한 건이 수천 토큰이다. 기본 타임아웃(5초)이면 전부 실패한다.
        self.timeout = float(options.get("timeout", 900))
        self.api_key = os.environ.get("XAI_API_KEY", "")

    def complete(self, system: str, prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("XAI_API_KEY 가 설정돼 있지 않습니다.")

        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            if resp.status_code >= 400:
                # 원문 본문에 사유가 담긴다(모델명 오타·크레딧 소진 등).
                # status_code 만 던지면 화면에서 원인을 알 수 없다.
                raise RuntimeError(
                    f"xAI API 오류 {resp.status_code}: {resp.text[:500]}"
                )
            data = resp.json()

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"xAI 응답에 choices 가 없습니다: {str(data)[:300]}")

        message = choices[0].get("message") or {}
        if message.get("refusal"):
            raise RuntimeError(f"모델이 요청을 거절했습니다: {message['refusal']}")

        content = message.get("content") or ""
        if not content.strip():
            # reasoning 모델이 max_tokens 를 추론에만 다 쓰면 본문이 빈다.
            # 그대로 두면 빈 명세서가 저장되므로 여기서 실패로 만든다.
            reason = choices[0].get("finish_reason")
            raise RuntimeError(
                f"xAI 응답 본문이 비어 있습니다 (finish_reason={reason}). "
                "max_tokens 를 늘리거나 non-reasoning 모델을 쓰십시오."
            )
        return content.strip()
