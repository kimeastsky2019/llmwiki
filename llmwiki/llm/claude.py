"""Claude API 공급자."""

from __future__ import annotations

from typing import Any

import anthropic


class ClaudeProvider:
    name = "claude"

    def __init__(self, options: dict[str, Any]) -> None:
        self.model = options.get("model", "claude-opus-5")
        self.max_tokens = int(options.get("max_tokens", 16000))
        self.effort = options.get("effort", "high")
        # ANTHROPIC_API_KEY 또는 `ant auth login` 프로필에서 자동 해석된다
        self.client = anthropic.Anthropic()

    def complete(self, system: str, prompt: str) -> str:
        # 산출물은 길다 → 스트리밍으로 받아 HTTP 타임아웃을 피한다.
        with self.client.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            output_config={"effort": self.effort},
            system=[
                {
                    "type": "text",
                    "text": system,
                    # 같은 시스템 프롬프트를 수백 번 재사용하므로 캐시한다
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            message = stream.get_final_message()

        if message.stop_reason == "refusal":
            detail = getattr(message, "stop_details", None)
            raise RuntimeError(
                f"모델이 요청을 거절했습니다 (category={getattr(detail, 'category', None)})"
            )

        return "".join(b.text for b in message.content if b.type == "text").strip()
