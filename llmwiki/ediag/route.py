"""모델 라우팅 — ACL 이 1순위, 태스크 난이도가 2순위 (P5).

보유 자산은 성격이 다른 둘이다.

| | 사내 모델 (Qwen 계열, ollama) | 외부 API (Grok·Claude) |
|---|---|---|
| 비용 | 고정비 — 한계비용 ≈ 0 | 토큰 과금 |
| 보안 | 외부 전송 없음 | **외부 전송 발생** |
| 강점 | 대량 반복·정형 변환 | 복잡 추론·다단계 |

판정 순서를 뒤집지 않는 것이 핵심이다. 태스크 난이도를 먼저 보면 "이건 어려우니까
외부로" 라는 판단이 `confidential` 문서에도 적용된다. 보안이 성능보다 먼저다.

    if acl in {confidential, restricted}:  → 사내 전용 (외부 호출 차단)
    else:                                  → 태스크 난이도로 2차 판정

이 모듈은 **정책만** 판정한다. 실제 호출은 `llmwiki/llm/` 이 한다 — 정책과 호출을
한곳에 두면 정책을 테스트할 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import contract

#: 외부로 나가지 않는 공급자. `llmwiki/kb/gate.py` 의 목적지 판정과 같은 축이다.
INTERNAL_PROVIDERS: tuple[str, ...] = ("ollama", "template")

#: 태스크별 기본 배정. 기획서 5.2 의 표가 그대로 코드가 된다.
TASK_TIER: dict[str, str] = {
    "parse": "code",              # LLM 을 부르지 않는다
    "frontmatter": "bulk",        # 정형 변환, 건수 많음
    "wiki_draft": "bulk",         # 문서당 반복
    "embedding": "bulk",
    "qa_simple": "bulk",
    "lint_autofix": "bulk",       # 대부분 기계적
    "concept": "frontier",        # 문서 간 연결·추상화
    "rewrite": "frontier",        # 원문 대조 재서술 — 규칙이 만든 거친 문장을 고친다
    "contradiction": "frontier",  # 다문서 교차 추론
    "qa_multihop": "frontier",    # "A공장과 B공장 원단위 차이 원인은?"
    "report_draft": "frontier",   # 최종 산출물 품질 직결
}

TIERS: tuple[str, ...] = ("code", "bulk", "frontier")


@dataclass
class Decision:
    task: str
    acl: str
    tier: str
    provider: str
    external_allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def decide(task: str, acl: str, *, internal_provider: str = "ollama",
           external_provider: str = "grok") -> Decision:
    """태스크 하나의 공급자를 정한다.

    모르는 태스크는 **막히는 쪽으로** 틀린다 — 사내 모델로 보낸다. 모르는 것을
    외부로 보내는 기본값은 언젠가 사고가 된다.
    """
    if acl not in contract.ACL_LEVELS:
        raise KeyError(f"정의되지 않은 접근 등급이다: {acl}")
    tier = TASK_TIER.get(task, "bulk")

    if tier == "code":
        return Decision(task, acl, tier, "code", False,
                        "LLM 이 필요 없는 단계다 — 파서와 계산 코드가 처리한다")

    if acl in contract.ACL_INTERNAL_ONLY:
        return Decision(task, acl, tier, internal_provider, False,
                        f"acl={acl} 이라 외부 호출을 차단한다 (P5). "
                        "난이도와 무관하게 사내 모델로만 처리한다")

    if tier == "frontier":
        return Decision(task, acl, tier, external_provider, True,
                        "문서 간 추론이 필요한 고난도 구간이라 외부 모델을 쓴다")

    return Decision(task, acl, tier, internal_provider, False,
                    "대량 반복 구간이라 한계비용이 0에 가까운 사내 모델로 처리한다")


def policy() -> dict[str, Any]:
    """화면·CLI 가 정책 전체를 조회하는 창구."""
    return {
        "order": ["acl", "task_tier"],
        "internal_only_acl": sorted(contract.ACL_INTERNAL_ONLY),
        "internal_providers": list(INTERNAL_PROVIDERS),
        "tiers": list(TIERS),
        "tasks": dict(sorted(TASK_TIER.items())),
    }
