"""LLM 공급자 추상화.

개발/데모는 Claude API, 고객사 망분리 환경은 사내 Ollama 로 전환한다.
config.yaml 의 llm.provider 한 줄만 바꾸면 된다.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, prompt: str) -> str:
        """system + prompt 를 넣고 최종 텍스트를 돌려준다."""
        ...


def get_provider(provider: str, options: dict[str, Any]) -> LLMProvider:
    if provider == "claude":
        from .claude import ClaudeProvider

        return ClaudeProvider(options)
    if provider == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(options)
    if provider == "template":
        from .template import TemplateProvider

        return TemplateProvider(options)
    raise ValueError(
        f"알 수 없는 LLM provider: {provider} (claude | ollama | template)"
    )
