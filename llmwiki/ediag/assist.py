"""서술 초안 제안 — LLM 이 **말**만 쓰고 **수**는 못 쓰게 한다.

기획서 5.2 의 분업이 여기서 실제로 돈다.

| 단계 | 담당 | 이유 |
|---|---|---|
| 파싱·계산·검산 | 코드 | LLM 이 필요 없다 |
| 대량 정형 변환 | 사내 모델 | 한계비용 ≈ 0 |
| **문서 간 연결·추상화** | **외부 모델(Grok)** | 고난도 구간, 전체의 10~20% |

이 모듈이 하는 일은 하나다 — 개선안 카드의 `[검토 필요]` 자리(적용 조건의 일반화,
검토 포인트)에 **초안 문장**을 제안한다. 그리고 세 겹으로 막는다.

1. **ACL 이 경로를 정한다.** `confidential` 이상은 외부로 나가지 않는다(P5).
   `route.decide()` 가 판정하고, 이 모듈에 우회 인자는 없다.
2. **외부 호출은 명시적 선택이 있어야 한다.** 화면에서 사내/외부를 고르지 않으면
   기본은 사내다. 선택이 곧 동의이므로, 고른 경로와 **실제로 탄 경로**를 함께
   돌려준다 — 등급 때문에 사내로 되돌려진 경우를 사용자가 알아야 한다.
3. **숫자는 출력에서 검산한다.** 원문에 없는 수가 답변에 나오면 그 수를 표시해
   돌려준다. 프롬프트로만 막으면 언젠가 새는데, 그 순간이 P2 가 깨지는 순간이다.

제안은 **페이지에 쓰지 않는다.** 사람이 검토 큐에서 보고 반영한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..llm import get_provider
from . import route
from .page import WikiPage

#: 이 모듈이 지원하는 태스크. route.TASK_TIER 의 키여야 라우팅이 판정할 수 있다.
TASKS: tuple[str, ...] = ("concept", "report_draft", "qa_multihop", "rewrite")

SYSTEM = (
    "너는 에너지 진단 보고서를 다루는 사내 지식 편집자다. "
    "규칙이 셋 있고, 어기면 결과가 폐기된다.\n"
    "1) 숫자를 새로 만들지 마라. 제공된 본문에 있는 값만 인용하고, "
    "필요한 값이 없으면 '확인 필요'라고 써라. 계산하지 마라 — 계산은 코드가 한다.\n"
    "2) 사업장·담당자를 특정할 수 있는 표현을 쓰지 마라. 개선안은 다른 사업장에서도 "
    "재사용되는 카드다.\n"
    "3) 근거가 없는 단정을 하지 마라. 조건부로 쓰고, 무엇을 확인해야 하는지 남겨라.\n"
    "출력은 한국어 마크다운이고, 요청받은 절만 쓴다."
)

PROMPTS: dict[str, str] = {
    "concept": (
        "아래 개선안 카드의 **적용 조건**을 일반화한 초안을 써라. "
        "이 사례에서 관측된 조건을 근거로, 어떤 사업장에 이 개선안이 맞는지 "
        "판단 기준을 3~5개 항목으로 제시한다. 각 항목 끝에 그 조건을 어디서 "
        "확인해야 하는지(계측·청구서·설계도서 등)를 괄호로 적는다."
    ),
    "report_draft": (
        "아래 페이지를 근거로 진단 보고서의 해당 절 초안을 써라. "
        "현황 → 문제점 → 개선방안 순서로 쓰되, 수치는 본문에 있는 값을 그대로 "
        "인용하고 없으면 '[검토 필요]'로 남긴다."
    ),
    "qa_multihop": (
        "아래 페이지들을 비교해 무엇이 다르고 왜 다른지 설명하는 초안을 써라. "
        "원인을 단정하지 말고 확인해야 할 항목으로 제시한다."
    ),
    # 재분석 — 규칙이 만든 페이지는 문장이 거칠다. 원문을 다시 보고 **서술만** 고친다.
    #
    # '보존하라'만 강하게 쓰면 모델이 몸을 사려 원문을 그대로 돌려준다. 그러면 재분석을
    # 부른 이유가 사라진다. 그래서 **무엇을 반드시 고쳐야 하는지**를 먼저 말하고,
    # 보존 대상을 그 뒤에 못 박는다.
    "rewrite": (
        "아래 위키 페이지의 **서술을 다시 써라.** 이 페이지는 규칙이 원문에서 문장을 잘라 "
        "붙인 것이라, 문장이 중간에서 끊기고 목록 번호 같은 흔적이 남아 있다.\n"
        "\n"
        "### 반드시 고칠 것\n"
        "- `## 요약` 은 원문 발췌를 근거로 **새로 쓴다.** 원래 문장을 그대로 두지 마라. "
        "무엇을 어떤 설비로 바꾸는 개선인지, 그래서 무엇이 좋아지는지가 두세 문장에 "
        "들어가야 한다.\n"
        "- 잘린 문장은 원문 발췌를 보고 잇는다. `- (p2) …유기질 공정의 노` 처럼 다음 "
        "줄로 넘어간 조각은 한 문장으로 합친다.\n"
        "- 원문에서 딸려온 목록 번호(`3)`, `가.`)와 어색한 문장부호는 지운다.\n"
        "- 원문 발췌에서 확인되는 맥락(공정 위치, 운전 조건, 문제의 원인)을 서술에 넣는다.\n"
        "\n"
        "### 절대 바꾸지 말 것\n"
        "- **표와 숫자.** 표는 한 글자도 바꾸지 말고 그대로 옮겨 붙인다. 본문의 수치도 "
        "있는 그대로 인용한다. 새 수치를 계산하거나 추정하지 마라 — 수치는 코드가 만든다.\n"
        "- 절 제목(`##`)과 순서. 절을 늘리거나 지우지 마라.\n"
        "- 인용문(`>`)과 `[[...]]` 위키 링크, `[검토 필요]` 표시.\n"
        "\n"
        "확인되지 않는 것은 지어내지 말고 `[검토 필요]` 로 남긴다.\n"
        "출력은 페이지 본문 마크다운 **전체**다. 다른 설명을 덧붙이지 마라."
    ),
}

#: 숫자 검사에서 무시할 값. 목록 번호·연도 같은 것까지 잡으면 경고가 소음이 된다.
_IGNORED_NUMBERS = frozenset({"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"})

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class Suggestion:
    stable_id: str
    task: str
    provider: str
    external: bool
    #: 화면이 고른 경로. provider 와 다르면 등급이나 설정이 끼어든 것이다.
    requested: str = ""
    text: str = ""
    decision: dict[str, Any] = field(default_factory=dict)
    #: 원문에 없는 수. 비어 있어야 그대로 반영할 수 있다.
    invented_numbers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def numeric_clean(self) -> bool:
        return not self.invented_numbers

    def to_dict(self) -> dict[str, Any]:
        return {
            "stable_id": self.stable_id,
            "task": self.task,
            "provider": self.provider,
            "requested": self.requested,
            "overridden": bool(self.requested and self.requested != self.provider),
            "external": self.external,
            "text": self.text,
            "decision": self.decision,
            "invented_numbers": self.invented_numbers,
            "numeric_clean": self.numeric_clean,
            "warnings": self.warnings,
            "applied": False,
        }


class AssistError(RuntimeError):
    """제안을 만들 수 없다. 조용히 빈 문자열을 돌려주지 않는다."""


def numbers_in(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in _NUMBER.finditer(text or "")}


def check_numbers(answer: str, source: str) -> list[str]:
    """답변에 원문에 없는 수가 있는가.

    프롬프트로만 막으면 언젠가 샌다. 출력에서 다시 본다 — P2 는 지시가 아니라
    검사로 지켜야 한다.
    """
    known = numbers_in(source)
    out = []
    for value in sorted(numbers_in(answer)):
        if value in known or value in _IGNORED_NUMBERS:
            continue
        # 소수 자리를 줄여 적는 경우(913.5671 → 913.57)는 원문 값의 접두사다.
        if any(k.startswith(value) or value.startswith(k) for k in known if len(k) >= 4):
            continue
        out.append(value)
    return out


def resolve_provider(cfg: Any, requested: str = "") -> tuple[str, bool]:
    """화면이 고른 공급자를 실제 공급자 이름으로 옮긴다.

    돌려주는 두 번째 값은 **사외로 나가는가**다. 화면이 `internal`/`external` 이라는
    말로 고르고 서버가 실제 이름을 정하는 이유는, 공급자가 늘거나 바뀔 때 화면을
    고치지 않아도 되게 하려는 것이다.
    """
    fallback_external = cfg.provider if cfg.provider not in route.INTERNAL_PROVIDERS else "grok"
    if not requested:
        # 고르지 않았으면 **사내**다. 기본값이 사외 전송이면 언젠가 모르고 내보낸다.
        return "ollama", False
    if requested == "auto":
        # 라우팅 판정에 맡긴다 — 난이도에 따라 외부로 갈 수 있다.
        return fallback_external, True
    if requested in ("internal", "sllm"):
        return "ollama", False
    if requested == "external":
        return fallback_external, True
    if requested in route.INTERNAL_PROVIDERS:
        return requested, False
    return requested, True


def suggest(page: WikiPage, *, cfg: Any, task: str = "concept",
            provider: str = "", allow_external: bool = False,
            context: str = "") -> Suggestion:
    """페이지 하나에 대한 서술 초안. 페이지를 고치지 않는다.

    `provider` 는 화면이 고른 경로다(`internal` · `external` · 공급자 이름).
    고르지 않으면 사내가 기본이고, 외부를 고른 것 자체가 사외 전송 동의다.
    다만 **등급이 이긴다** — `confidential` 이상은 무엇을 고르든 사내로 간다.
    """
    if task not in TASKS:
        raise AssistError(f"지원하지 않는 태스크다: {task} (허용: {', '.join(TASKS)})")

    external_provider, wants_external = resolve_provider(cfg, provider)
    if not provider and allow_external:
        # 예전 인자. 선택 UI 가 없던 시절의 호출을 그대로 받아 준다.
        wants_external = True
    requested = external_provider if wants_external else "ollama"

    decision = route.decide(task, page.acl, external_provider=external_provider)
    if decision.external_allowed and not wants_external:
        # 등급은 외부를 허용하지만 사용자가 사내를 골랐다. 사용자의 선택이 더 좁으므로
        # 그대로 따른다 — 더 넓히는 방향으로만 서버가 개입한다.
        decision = route.Decision(
            task=task, acl=page.acl, tier=decision.tier, provider="ollama",
            external_allowed=False,
            reason="화면에서 사내 모델을 골랐다 — 등급이 허용해도 사외로 내보내지 않는다")
    if not decision.external_allowed and decision.provider in route.INTERNAL_PROVIDERS:
        # 사내 경로다. 사내 모델이 설정돼 있지 않으면 여기서 멈춘다 —
        # 조용히 외부로 넘기면 P5 가 깨진다.
        if decision.provider not in cfg.providers:
            raise AssistError(
                f"acl={page.acl} 이라 사내 모델로만 처리할 수 있는데 "
                f"'{decision.provider}' 설정이 없다. config.yaml 의 llm 을 먼저 채운다.")

    source = "\n".join([page.title, page.body, context]).strip()
    prompt = (
        f"{PROMPTS[task]}\n\n"
        f"--- 페이지: {page.stable_id} ({page.type}) ---\n{page.body}\n--- 끝 ---"
    )
    if context:
        # 원문 발췌가 재분석의 실질이다. 페이지 본문만 주면 모델은 이미 거칠어진
        # 문장을 다시 다듬을 뿐, 빠진 맥락을 채우지 못한다.
        prompt += f"\n\n--- 원문 발췌 (근거) ---\n{context}\n--- 끝 ---"

    provider = get_provider(decision.provider, cfg.with_provider(decision.provider).llm_options)
    try:
        text = provider.complete(SYSTEM, prompt)
    except Exception as exc:  # noqa: BLE001 - 공급자 오류를 그대로 화면에 보여 준다
        raise AssistError(f"{decision.provider} 호출 실패: {exc}") from exc

    s = Suggestion(
        stable_id=page.stable_id, task=task, provider=decision.provider,
        external=decision.external_allowed, requested=requested, text=text,
        decision=decision.to_dict(), invented_numbers=check_numbers(text, source))
    if s.requested != s.provider:
        s.warnings.append(
            f"고른 경로는 {s.requested} 였지만 실제로는 {s.provider} 로 처리했다 — "
            f"{decision.reason}")
    if s.invented_numbers:
        s.warnings.append(
            "원문에 없는 수가 답변에 있다: " + ", ".join(s.invented_numbers[:8])
            + " — 그대로 반영하지 말 것. 수치는 코드가 계산한 값만 쓴다 (P2).")
    if page.acl in ("confidential", "restricted") and s.external:
        # 도달할 수 없는 조합이지만, 라우팅이 바뀌면 여기서 먼저 걸린다.
        s.warnings.append("접근 등급과 외부 호출이 함께 잡혔다 — 라우팅 설정을 확인한다.")
    return s


# --------------------------------------------------------------------------- #
# 재분석 — 원문 발췌를 근거로 서술을 다시 쓴다
# --------------------------------------------------------------------------- #
#: 재분석 결과에서 절 제목이 사라지면 페이지 구조가 무너진다. 최소한 이만큼은 남아야 한다.
MIN_HEADINGS = 2


def source_excerpt(page: WikiPage, chunks: list[dict[str, Any]], *,
                   max_chars: int = 6000) -> str:
    """페이지가 인용한 쪽의 원문만 골라 붙인다.

    문서 전체를 넣으면 32면짜리 보고서가 통째로 들어가 모델이 엉뚱한 쪽을 근거로 쓴다.
    `source_span` 이 가리키는 쪽만 준다 — 그게 이 페이지의 근거이기 때문이다.
    청크는 **이미 비식별된** 것이다(kb 저장소가 마스킹 후에만 적재한다).
    """
    wanted: set[int] = set()
    for span in page.source_span:
        for p in span.get("pages") or []:
            try:
                wanted.add(int(p))
            except (TypeError, ValueError):
                continue
    if not wanted:
        return ""

    parts: list[str] = []
    size = 0
    for chunk in chunks:
        page_no = chunk.get("page")
        if page_no is None or int(page_no) not in wanted:
            continue
        body = str(chunk.get("content", "")).strip()
        if not body:
            continue
        head = f"[p.{page_no} · {chunk.get('channel', '')}]"
        if size + len(body) > max_chars:
            body = body[: max(0, max_chars - size)]
        parts.append(f"{head}\n{body}")
        size += len(body)
        if size >= max_chars:
            break
    return "\n\n".join(parts)


def structure_kept(before: str, after: str) -> tuple[bool, list[str]]:
    """절 제목이 유지됐는가. 모델이 구조를 갈아엎으면 그 결과는 쓸 수 없다."""
    heads = lambda text: [l.strip() for l in text.splitlines() if l.strip().startswith("#")]
    original, produced = heads(before), heads(after)
    missing = [h for h in original if h not in produced]
    ok = len(produced) >= MIN_HEADINGS and not missing
    return ok, missing


def reanalyze(page: WikiPage, *, cfg: Any, chunks: list[dict[str, Any]] | None = None,
              provider: str = "") -> Suggestion:
    """페이지 하나를 원문 근거와 함께 다시 쓴다. **저장하지 않는다.**

    돌려주는 것은 제안이고, 반영은 사람이 `apply` 로 한다. 자동 반영하지 않는 이유는
    검토가 끝난 페이지가 조용히 바뀌면 그 서명이 무엇을 보증하는지 알 수 없기 때문이다.
    """
    context = source_excerpt(page, chunks or [])
    s = suggest(page, cfg=cfg, task="rewrite", provider=provider, context=context)
    if not context:
        s.warnings.append(
            "원문 발췌를 찾지 못해 페이지 본문만 보고 다시 썼다 — 빠진 맥락은 채워지지 "
            "않는다. 지식 데이터베이스에 이 문서를 적재하면 원문을 근거로 다시 쓸 수 있다.")
    ok, missing = structure_kept(page.body, s.text)
    if not ok:
        s.warnings.append(
            "절 구조가 유지되지 않았다"
            + (f" (사라진 제목: {', '.join(missing[:3])})" if missing else "")
            + " — 그대로 반영하면 페이지 형식이 무너진다.")
    s.decision["structure_kept"] = ok
    return s
