"""위험 식별·완화 검토를 돕는 sLM 조언자.

**모델은 판정하지 않는다.** 위험 식별 Yes/No 와 잔여 평가는 사람이 누르고,
점수·등급은 룰이 계산한다. 여기서 모델이 하는 일은 하나뿐이다 —
*사람이 그 버튼을 누르기 전에 무엇을 봐야 하는지* 를 정리해 주는 것.

그래서 응답 스키마에 verdict·identified·score 가 없다. 모델이 판정을 뱉을
자리를 아예 만들지 않는다. 자리를 만들어 두면 언젠가 그 값이 화면에 흘러들고,
그 순간 "같은 입력이면 같은 등급" 이라는 성질이 사라진다.

공급자 순서
----------
사내 sLM(ollama) 을 먼저 쓴다. 소스와 사내 문서가 서버 밖으로 나가지 않기
때문이다. 사내 모델이 준비 안 됐거나 실패하면 외부 API 로 넘길 수 있는데,
그건 **요청자가 명시적으로 허용했을 때만** 한다 — 프롬프트에 운영 소스의
테이블명·URL 이 들어가므로 조용히 넘기면 자료 유출이다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..llm import check as check_provider, get_provider
from . import riskassess

#: 사내에서 도는 공급자. 이 목록에 있으면 프롬프트가 서버 밖으로 나가지 않는다.
LOCAL_PROVIDERS = ("ollama",)


@dataclass
class Advice:
    item_no: int
    stage: str                     # "identify" | "mitigate"
    relevance: str = "unclear"     # 관련성 — 판정이 아니다
    summary: str = ""
    checkpoints: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    mitigations: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    local: bool = True
    fell_back: bool = False
    tried: list[dict[str, str]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_no": self.item_no,
            "stage": self.stage,
            "relevance": self.relevance,
            "summary": self.summary,
            "checkpoints": list(self.checkpoints),
            "evidence": list(self.evidence),
            "mitigations": list(self.mitigations),
            "provider": self.provider,
            "model": self.model,
            "local": self.local,
            "fell_back": self.fell_back,
            "tried": list(self.tried),
            "error": self.error,
            # 이 블록은 모델이 쓴 서술이다. 룰이 계산한 숫자와 섞이면 안 된다.
            "derivation": "llm",
        }


SYSTEM = """너는 금융회사의 AI 위험평가를 돕는 **조언자**다. 판정자가 아니다.

지켜야 할 것:
1. **판정하지 마라.** "위험이 있다/없다", "몇 점이다", "몇 등급이다" 를 말하지 마라.
   그 판단은 사람이 하고 점수는 룰이 계산한다. 네가 답할 것은
   "사람이 판단하려면 무엇을 봐야 하는가" 뿐이다.
2. **주어진 사실만 쓴다.** 아래 '코드 분석 사실' 에 없는 테이블·API·기능을
   지어내지 마라. 모르면 "확인 필요" 라고 적어라.
3. 짧게 써라. 각 항목은 한 문장이다. 미사여구를 넣지 마라.
4. 한국어로 답하라.

출력은 JSON 객체 하나뿐이다. 설명을 덧붙이지 마라.
{
  "relevance": "high" | "medium" | "low" | "unclear",
  "summary": "이 위험 항목이 이 서비스와 어떻게 닿는지 두 문장 이내",
  "checkpoints": ["판단 전에 확인할 것", "..."],
  "evidence": ["어떤 문서·기록을 보면 확인되는지", "..."]%s
}

relevance 는 판정이 아니라 **관련성**이다. 이 항목을 눈여겨봐야 하는 정도일 뿐,
위험이 있다는 뜻이 아니다."""

MITIGATION_FIELD = """,
  "mitigations": ["이 업계에서 통상 쓰는 완화 방안", "..."]"""

USER = """[위험 항목]
번호 {no} · {lv1} > {lv2} > {lv3}
배점 {points}점 · 담당 {owner}

[대상 서비스]
{service}

[서비스 프로파일]
{profile}

[코드 분석 사실]
{facts}

{extra}"""


def _facts_block(facts: dict[str, Any]) -> str:
    """정적 분석이 확인한 것만 넣는다. 없으면 없다고 적는다."""
    if not facts:
        return "(연결된 운영 프로그램이 없다. 코드 근거 없이 검토해야 한다.)"
    lines: list[str] = []
    if facts.get("programs"):
        lines.append("프로그램: " + ", ".join(facts["programs"][:12]))
    if facts.get("urls"):
        lines.append("호출 URL: " + ", ".join(facts["urls"][:12]))
    if facts.get("tables"):
        lines.append("접근 테이블: " + ", ".join(facts["tables"][:20]))
    if facts.get("crud"):
        lines.append("테이블 CRUD: " + ", ".join(
            f"{t}({''.join(sorted(ops))})" for t, ops in list(facts["crud"].items())[:16]
        ))
    if facts.get("layers"):
        lines.append("계층: " + ", ".join(facts["layers"]))
    return "\n".join(lines) or "(추출된 사실이 없다.)"


def build_prompt(
    item_no: int, *, stage: str, service: str, profile: dict[str, str],
    facts: dict[str, Any], identified_note: str = "",
) -> tuple[str, str]:
    spec = next((i for i in riskassess.items() if int(i["no"]) == item_no), None)
    if spec is None:
        raise KeyError(f"위험 항목 번호를 찾을 수 없다: {item_no}")

    system = SYSTEM % (MITIGATION_FIELD if stage == "mitigate" else "")
    extra = ""
    if stage == "mitigate":
        extra = (
            "[상황]\n이 항목은 위험으로 이미 식별됐다. 완화 방안을 검토하는 단계다.\n"
            "완화가 충분한지(잔여위험 없음/일부 남음/그대로)는 사람이 정한다.\n"
        )
        if identified_note:
            extra += f"검토자 메모: {identified_note}\n"

    user = USER.format(
        no=spec["no"], lv1=spec["lv1"], lv2=spec["lv2"], lv3=spec["lv3"],
        points=spec["points"], owner=spec["owner"],
        service=service or "(서비스명 미입력)",
        profile=", ".join(f"{k}={v}" for k, v in profile.items()) or "(미선택)",
        facts=_facts_block(facts),
        extra=extra,
    )
    return system, user


def _parse(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_list(value: Any, limit: int = 8) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:limit]


def provider_chain(cfg: Config, *, allow_external: bool) -> list[str]:
    """사내 → 외부 순서. 외부는 허용했을 때만 목록에 들어간다."""
    names = list(cfg.providers)
    local = [n for n in names if n in LOCAL_PROVIDERS]
    external = [n for n in names if n not in LOCAL_PROVIDERS and n != "template"]
    # 설정 기본 공급자를 외부 중 맨 앞에 둔다 — 운영자가 고른 순서를 존중한다
    external.sort(key=lambda n: 0 if n == cfg.raw.get("llm", {}).get("provider") else 1)
    return local + (external if allow_external else [])


def advise(
    cfg: Config,
    *,
    item_no: int,
    stage: str = "identify",
    service: str = "",
    profile: dict[str, str] | None = None,
    facts: dict[str, Any] | None = None,
    identified_note: str = "",
    allow_external: bool = False,
) -> Advice:
    """한 항목에 대한 조언. 실패해도 예외를 던지지 않고 error 에 담는다.

    화면에서 조언은 '있으면 좋은 것' 이다. LLM 이 죽었다고 평가 자체가 막히면
    안 되므로, 실패를 결과의 한 필드로 돌려준다.
    """
    out = Advice(item_no=item_no, stage=stage)
    system, user = build_prompt(
        item_no, stage=stage, service=service, profile=profile or {},
        facts=facts or {}, identified_note=identified_note,
    )

    chain = provider_chain(cfg, allow_external=allow_external)
    if not chain:
        out.error = (
            "사내 LLM 을 쓸 수 없습니다. 외부 API 로 넘기려면 '외부 API 허용' 을 켜십시오."
        )
        return out

    for index, name in enumerate(chain):
        pcfg = cfg.with_provider(name)
        ready = check_provider(name, pcfg.llm_options)
        if not ready.ok:
            out.tried.append({"provider": name, "error": ready.reason})
            continue
        try:
            provider = get_provider(name, pcfg.llm_options)
            raw = provider.complete(system, user)
        except Exception as exc:  # noqa: BLE001 — 어떤 공급자든 다음으로 넘긴다
            out.tried.append({"provider": name, "error": str(exc)[:200]})
            continue

        parsed = _parse(raw)
        if not parsed:
            out.tried.append({"provider": name, "error": "응답을 JSON 으로 읽지 못했다"})
            continue

        relevance = str(parsed.get("relevance", "unclear")).lower()
        out.relevance = relevance if relevance in ("high", "medium", "low", "unclear") else "unclear"
        out.summary = str(parsed.get("summary", "")).strip()
        out.checkpoints = _as_list(parsed.get("checkpoints"))
        out.evidence = _as_list(parsed.get("evidence"))
        out.mitigations = _as_list(parsed.get("mitigations")) if stage == "mitigate" else []
        out.provider = name
        out.model = str(pcfg.llm_options.get("model", ""))
        out.local = name in LOCAL_PROVIDERS
        # 사내 모델이 첫 순서인데 그걸 못 쓰고 넘어왔으면 알려 준다
        out.fell_back = index > 0
        return out

    out.error = "조언을 받지 못했습니다. 아래 시도 기록을 보십시오."
    return out
