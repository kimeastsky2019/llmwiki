"""LLM 공급자가 실제로 호출 가능한 상태인지 미리 확인한다.

이게 없으면 명세서 생성 버튼을 누른 뒤에야 SDK 원문 오류를 보게 된다.
("Could not resolve authentication method. Expected one of api_key …")
무엇을 어떻게 고쳐야 하는지가 전혀 안 담긴 메시지라, 여기서 번역한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class Readiness:
    ok: bool
    reason: str = ""      # 왜 못 쓰는지 (한 줄)
    hint: str = ""        # 어떻게 고치는지 (여러 줄 가능)
    detail: str = ""      # 원문 오류 (진단용)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "hint": self.hint, "detail": self.detail}


CLAUDE_HINT = """다음 중 하나를 고르십시오.

1) API 키 설정 — 서버를 띄운 터미널에서:
     export ANTHROPIC_API_KEY=sk-ant-...
   그리고 `llmwiki serve` 를 다시 실행하십시오.

2) 사내 Ollama 사용 — config.yaml 에서:
     llm:
       provider: ollama
   또는 환경변수 LLMWIKI_PROVIDER=ollama 로 서버를 띄우십시오.
   (금융·공공 소스는 클라우드 API 로 보내지 마십시오.)

3) LLM 없이 구조만 보기 — LLMWIKI_PROVIDER=template
   URL·클래스·테이블·CRUD·흐름도·영향도는 그대로 나오고,
   서술 항목만 '(LLM 생성 필요)' 로 비워집니다."""


GROK_HINT = """다음 중 하나를 고르십시오.

1) API 키 설정 — 서버를 띄운 터미널에서:
     export XAI_API_KEY=xai-...
   그리고 `llmwiki serve` 를 다시 실행하십시오.
   (systemd 로 띄웠다면 유닛의 EnvironmentFile 을 확인하십시오.)

2) 사내 Ollama 사용 — config.yaml 에서:
     llm:
       provider: ollama
   (금융·공공 소스는 클라우드 API 로 보내지 마십시오.)

3) LLM 없이 구조만 보기 — LLMWIKI_PROVIDER=template"""


def check(provider: str, options: dict[str, Any]) -> Readiness:
    if provider == "claude":
        return _check_claude()
    if provider == "grok":
        return _check_grok(options)
    if provider == "ollama":
        return _check_ollama(options)
    if provider == "template":
        return Readiness(ok=True)
    return Readiness(
        ok=False,
        reason=f"알 수 없는 provider: {provider}",
        hint="claude · grok · ollama · template 중 하나여야 합니다.",
    )


def _check_claude() -> Readiness:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Readiness(ok=True)
    try:
        import anthropic

        # 클라이언트 '생성'은 키가 없어도 성공한다. 실패는 요청 시점에 나므로
        # 해석된 자격증명이 실제로 있는지를 직접 본다.
        client = anthropic.Anthropic()
    except Exception as exc:  # noqa: BLE001
        return Readiness(
            ok=False,
            reason="Claude 클라이언트를 만들 수 없습니다.",
            hint=CLAUDE_HINT,
            detail=str(exc),
        )

    if client.api_key or getattr(client, "auth_token", None) or client.auth_headers:
        return Readiness(ok=True)
    return Readiness(
        ok=False,
        reason="Claude API 키가 없습니다 (ANTHROPIC_API_KEY 미설정).",
        hint=CLAUDE_HINT,
        detail=(
            "anthropic SDK 가 api_key / auth_token 을 찾지 못했습니다. "
            "생성 요청 시 'Could not resolve authentication method' 로 실패합니다."
        ),
    )


# 성공한 확인만 기억한다. /api/meta 가 화면 전환마다 불려서, 그때마다
# 외부 API 를 왕복하면 뷰어가 눈에 띄게 굼떠진다. 실패는 캐시하지 않는다
# — 키를 고치고 서버를 다시 띄우지 않아도 바로 반영되도록.
_grok_ok: set[tuple[str, str]] = set()


def _check_grok(options: dict[str, Any]) -> Readiness:
    key = os.environ.get("XAI_API_KEY", "")
    if not key:
        return Readiness(
            ok=False,
            reason="xAI(Grok) API 키가 없습니다 (XAI_API_KEY 미설정).",
            hint=GROK_HINT,
        )

    base = str(
        options.get("base_url") or os.environ.get("XAI_BASE_URL") or "https://api.x.ai/v1"
    ).rstrip("/")
    model = str(options.get("model") or os.environ.get("XAI_MODEL") or "")
    if (base, model) in _grok_ok:
        return Readiness(ok=True)

    try:
        resp = httpx.get(
            f"{base}/models", headers={"Authorization": f"Bearer {key}"}, timeout=8
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
    except Exception as exc:  # noqa: BLE001
        return Readiness(
            ok=False,
            reason=f"xAI API 에 연결할 수 없습니다: {base}",
            hint=(
                "키가 유효한지, 서버에서 외부 인터넷이 나가는지 확인하십시오.\n"
                "망분리 환경이면 config.yaml 의 llm.provider 를 ollama 로 바꾸십시오."
            ),
            detail=str(exc),
        )

    # 별칭(grok-4.20 → grok-4.20-0309-reasoning)도 유효한 이름이다.
    names = {m.get("id", "") for m in data}
    for m in data:
        names.update(m.get("aliases") or [])
    if model and model not in names:
        return Readiness(
            ok=False,
            reason=f"xAI 에 '{model}' 모델이 없습니다.",
            hint=(
                "config.yaml 의 llm.grok.model 또는 환경변수 XAI_MODEL 을\n"
                f"사용 가능한 모델로 바꾸십시오. 사용 가능: "
                f"{', '.join(sorted(m.get('id', '') for m in data)) or '(없음)'}"
            ),
        )

    _grok_ok.add((base, model))
    return Readiness(ok=True)


def _check_ollama(options: dict[str, Any]) -> Readiness:
    base = str(options.get("base_url", "http://localhost:11434")).rstrip("/")
    model = options.get("model", "")
    try:
        resp = httpx.get(f"{base}/api/tags", timeout=5)
        resp.raise_for_status()
        names = [m.get("name", "") for m in resp.json().get("models", [])]
    except Exception as exc:  # noqa: BLE001
        return Readiness(
            ok=False,
            reason=f"Ollama 서버에 연결할 수 없습니다: {base}",
            hint=(
                "서버가 떠 있는지, 사내망/VPN 이 연결돼 있는지 확인하십시오.\n"
                "로컬에서 쓰려면 `ollama serve` 후 config.yaml 의\n"
                "  llm.ollama.base_url: \"http://localhost:11434\" 로 바꾸십시오."
            ),
            detail=str(exc),
        )
    if model and model not in names and not any(n.startswith(f"{model}:") for n in names):
        return Readiness(
            ok=False,
            reason=f"Ollama 에 '{model}' 모델이 없습니다.",
            hint=(
                f"`ollama pull {model}` 로 받거나, config.yaml 의 llm.ollama.model 을\n"
                f"설치된 모델로 바꾸십시오. 현재 설치됨: {', '.join(names) or '(없음)'}"
            ),
        )
    return Readiness(ok=True)
