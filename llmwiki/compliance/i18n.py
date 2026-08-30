"""규제 화면으로 나가는 문자열의 한국어·영어 대응.

여기 있는 것은 **사람이 읽는 문장**뿐이다. 그래프에 저장되는 값(verdict 코드,
level, decision_status)은 언어와 무관한 영어 상수로 두고, 화면에 찍을 때만
이 표를 거친다. 값 자체를 번역하면 같은 사실이 언어마다 다른 데이터가 된다.

판정 사유는 조각을 모아 만든다. 통째로 문장을 두지 않는 이유는, 사유가
'필수 증적 1/2 · 만료 임박 A, B' 처럼 상황에 따라 조합이 달라지기 때문이다.
"""

from __future__ import annotations

from typing import Any

LANGS = ("ko", "en")
DEFAULT_LANG = "ko"


def normalize(lang: str | None) -> str:
    """모르는 값이 오면 기본 언어로. 화면이 빈 문자열을 보지 않게 한다."""
    return lang if lang in LANGS else DEFAULT_LANG


#: 판정 라벨. 코드(SATISFIED 등)는 데이터, 여기 값은 표시용이다.
VERDICT: dict[str, dict[str, str]] = {
    "ko": {
        "SATISFIED": "충족",
        "PARTIAL": "부분충족",
        "UNSATISFIED": "미충족",
        "NOT_APPLICABLE": "해당없음",
        "DEFERRED": "판단유보",
    },
    "en": {
        "SATISFIED": "Satisfied",
        "PARTIAL": "Partially satisfied",
        "UNSATISFIED": "Not satisfied",
        "NOT_APPLICABLE": "Not applicable",
        "DEFERRED": "Deferred to reviewer",
    },
}

#: 의무의 강제력 표시. 값 자체는 mandatory/recommended 로 저장된다.
LEVEL: dict[str, dict[str, str]] = {
    "ko": {"mandatory": "필수", "recommended": "권고"},
    "en": {"mandatory": "Mandatory", "recommended": "Recommended"},
}

#: 판정의 결재 상태.
DECISION: dict[str, dict[str, str]] = {
    "ko": {"provisional": "잠정", "confirmed": "확정"},
    "en": {"provisional": "Provisional", "confirmed": "Confirmed"},
}

#: 판단 유보 트리거 — 정밀도 우선. 애매하면 사람에게 넘긴다.
TRIGGER: dict[str, dict[str, str]] = {
    "ko": {
        "QUALITATIVE": "통제의 auto_level 이 L3 — 정성 판단이 필요하다",
        "PARTIAL_EVIDENCE": "필요 증적 중 일부만 있다 — 충족 여부가 실질 판단에 달렸다",
        "THRESHOLD_UNDEFINED": "지표는 있으나 임계치가 정해져 있지 않다",
        "METRIC_MISSING": "임계치는 있으나 측정값이 없다",
        "EVIDENCE_EXPIRING": "증적 유효기간이 30일 안에 끝난다",
        "PROVISION_AMENDING": "참조 조문이 개정 중이다 — 기준 자체가 흔들린다",
        "VERDICT_FLIPPED": "직전 차수와 판정이 뒤집혔다 — 변경 사유를 확인해야 한다",
        "CITATION_WEAK": "인용 강도 검증에 실패했다 — 주장이 근거보다 세다",
        "TEMPLATE_UNFILLED": "서식의 자리표시자가 그대로 남아 있다 — 미기입으로 보이나 "
                             "예시문일 수 있어 사람이 확인해야 한다",
        "DOC_CONFLICT": "같은 값을 말하는 문서끼리 값이 다르다 — 어느 쪽이 맞는지 "
                        "사람이 정한다",
    },
    "en": {
        "QUALITATIVE": "Control is auto_level L3 — needs human judgement",
        "PARTIAL_EVIDENCE": "Only some required evidence is present — sufficiency is a "
                            "judgement call",
        "THRESHOLD_UNDEFINED": "Metric exists but no threshold is defined",
        "METRIC_MISSING": "Threshold is defined but no measurement was found",
        "EVIDENCE_EXPIRING": "Evidence expires within 30 days",
        "PROVISION_AMENDING": "Cited provision is being amended — the standard itself "
                              "is in flux",
        "VERDICT_FLIPPED": "Verdict flipped since the previous run — the reason for "
                           "the change needs checking",
        "CITATION_WEAK": "Citation-strength check failed — the claim is stronger than "
                         "the quoted text supports",
        "TEMPLATE_UNFILLED": "Template placeholders are still in place — looks "
                             "unfilled, but may be sample text, so a human must confirm",
        "DOC_CONFLICT": "Documents asserting the same value disagree — a human decides "
                        "which one holds",
    },
}

#: 판정 사유 조각. {} 자리는 rules 가 채운다.
REASON: dict[str, dict[str, str]] = {
    "ko": {
        "head": "룰 판정 {verdict}",
        "deferred_arrow": " → 판단유보",
        "no_control": "통제 {code} 가 승인 그래프에 없거나 폐기됐다",
        "not_applied": "이 서비스에 적용되지 않는 통제",
        "evidence": "필수 증적 {have}/{need}",
        "metric": "지표·구성 {passed}/{total}",
        "missing_sections": "빠진 절: {items}",
        "unfilled": "미기입 의심: {items}",
        "conflict": "문서 간 불일치: {items}",
        "qualitative": "정성 항목 — 룰이 판정하지 않는다",
        "nothing_required": "요구 증적·지표 없음",
        "rejected": "불인정: {items}",
        "expiring": "만료 임박: {items}",
        "threshold_undefined": "임계치 미정: {items}",
        "metric_missing": "측정값 없음: {items}",
        "unsigned": "서명 없음",
        "not_yet_valid": "유효기간 시작 전",
        "expired": "유효기간 만료",
        "section_ok": "구성 검토 통과 ({n}절)",
        "section_gap": "빠진 절 {n}개: {items}",
        "metric_met": "{metric} {value}{unit} {op} {threshold} 충족",
        "metric_not_met": "{metric} {value}{unit} {op} {threshold} 미충족",
    },
    "en": {
        "head": "Rule verdict: {verdict}",
        "deferred_arrow": " → deferred to reviewer",
        "no_control": "Control {code} is absent from the approved graph or retired",
        "not_applied": "Control does not apply to this service",
        "evidence": "required evidence {have}/{need}",
        "metric": "metric/section checks {passed}/{total}",
        "missing_sections": "missing sections: {items}",
        "unfilled": "possibly unfilled: {items}",
        "conflict": "documents disagree: {items}",
        "qualitative": "qualitative control — rules do not decide it",
        "nothing_required": "no evidence or metric required",
        "rejected": "rejected: {items}",
        "expiring": "expiring soon: {items}",
        "threshold_undefined": "threshold undefined: {items}",
        "metric_missing": "measurement missing: {items}",
        "unsigned": "unsigned",
        "not_yet_valid": "not yet valid",
        "expired": "expired",
        "section_ok": "section check passed ({n} sections)",
        "section_gap": "{n} sections missing: {items}",
        "metric_met": "{metric} {value}{unit} {op} {threshold} met",
        "metric_not_met": "{metric} {value}{unit} {op} {threshold} not met",
    },
}

#: 커버리지 갭 화면의 설명.
COVERAGE: dict[str, dict[str, str]] = {
    "ko": {
        "partial": "통제가 의무를 일부만 덮는다",
        "manual": "증적을 생산하는 시스템 기능이 없다 — 수기 의존, 자동화 후보",
    },
    "en": {
        "partial": "control covers the obligation only in part",
        "manual": "no system function produces this evidence — manual today, "
                  "candidate for automation",
    },
}


def t(table: dict[str, dict[str, str]], lang: str, key: str, **fmt: Any) -> str:
    """카탈로그에서 한 줄 꺼내 포맷한다. 없는 키는 키 자체를 돌려준다."""
    lang = normalize(lang)
    text = table.get(lang, {}).get(key) or table.get(DEFAULT_LANG, {}).get(key) or key
    return text.format(**fmt) if fmt else text


def verdict_labels(lang: str) -> dict[str, str]:
    return dict(VERDICT[normalize(lang)])
