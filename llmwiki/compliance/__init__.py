"""근거기반 자동평가 엔진 및 규제 지식그래프.

한 문장 요약: **LLM은 그래프를 채우고, 판정은 그래프 위의 룰이 한다.**

LLMWiki 본체가 "운영 소스 → 사실 그래프 → 서술" 을 하는 것과 같은 원칙을
규제 영역에 적용한다. 사실(정적 추출)과 서술(모델)을 갈라 두고, 판정은
사실 위에서 결정론적으로 계산한다.

계층
----
L0 수집    `propose.scan_provisions` — 문서를 불변 앵커와 함께 적재
L1 이해    `propose` — sLM 이 근거 스팬을 붙여 **그래프 변경 제안**만 만든다
L2 그래프  `store` — 승인된 사실. 삭제 없음, 양시간, as_of 재현
L3 판정    `rules` — 승인 그래프 위의 결정론적 룰. LLM 없음
L4 검증    `verify` — 형상 검증 · 인용 강도 · 골드셋 회귀 · Cohen κ
L5 분석    `analysis` — 커버리지 갭 · 규제 변경 영향 · 수기 의존 통제
L6 결재    `changeset` — diff 리뷰와 승인. 승인본/제안본 물리 분리
"""

from .ontology import (
    COMPLIANCE_ONTOLOGY_VERSION,
    EDGE_TYPES,
    NODE_TYPES,
    VERDICTS,
    node_id,
    schema_dict,
)

__all__ = [
    "COMPLIANCE_ONTOLOGY_VERSION",
    "EDGE_TYPES",
    "NODE_TYPES",
    "VERDICTS",
    "node_id",
    "schema_dict",
]
