"""업종 자동 분류 — 규칙이 판정하고, 애매하면 사람에게 넘긴다.

**LLM 에게 분류를 묻지 않는다**는 것이 이 모듈의 설계다. 자유 서술로 라벨을 받으면
같은 보고서가 적재할 때마다 다른 업종을 받고, 그 순간 업종별 구획 분리와 업종별
필수지표 점검이 전부 무너진다.

  1. 어휘 규칙으로 점수를 낸다 (결정론적, 재현 가능)
  2. 1·2위 점수차가 충분하면 **그대로 확정**한다
  3. 애매하면 확정하지 않고 ``needs_review=True`` 로 사람에게 넘긴다

정밀도 우선이다. 커버리지를 늘리려다 잘못 분류하면 그 문서는 영영 엉뚱한 구획에서
검색된다 — **틀린 라벨은 없는 라벨보다 나쁘다.** 규제 지식그래프가 L3(정성 판단)을
룰로 확정하지 않는 것과 같은 처리다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import taxonomy

#: 1·2위 점수차가 이 값 미만이면 확정하지 않는다.
MARGIN_THRESHOLD = 0.25

#: 최소 이만큼은 맞아야 분류를 시도한다.
MIN_SCORE = 3.0

#: 분류 방법의 닫힌 집합. rule 이 기본이고, manual 은 사람이 지정한 것이다.
METHODS: tuple[str, ...] = ("rule", "manual", "fallback")

#: 업종과 무관하게 **모든 에너지진단서에 나오는** 유틸리티 설비·용어.
#:
#: 진단은 애초에 이 설비들을 들여다보는 일이라, 어느 공장 보고서를 열어도
#: 보일러·압축기·펌프·조명이 수십~수백 번 나온다. 이걸 업종 신호로 세면
#: 등장 횟수가 많은 쪽이 이겨서 **모든 공장이 '건물' 로 분류된다**
#: (실측: 5개 진단서 중 4건이 건물로 확정, 근거가 전부 공조·냉동기·조명이었다).
#: 업종을 가르는 것은 유틸리티가 아니라 공정 어휘다.
GENERIC_UTILITY: frozenset[str] = frozenset({
    "보일러", "압축기", "펌프", "열교환기", "냉동기", "공조기", "공조", "냉동",
    "조명", "송풍기", "송풍", "집진기", "승강기", "난방기", "제습기", "건조기",
    "연면적",
    # '전기로' 는 '전기로 인한' 의 앞부분과 구별되지 않는다.
    "전기로",
})

#: 힌트가 더 긴 낱말 안에 박혀 생기는 오탐.
#:
#: 한국어는 낱말 경계가 없어 부분문자열이 그대로 걸린다. 진단서에는 온실가스
#: 감축량이 늘 나오므로 '온실' 을 그대로 세면 모든 문서가 농업으로 기운다
#: (실측: 한 보고서에서 '온실' 99회 중 92%가 '온실가스' 였다).
#: 값은 '이 말이 나오면 그 자리는 힌트가 아니다' 라는 뜻이다.
HINT_TRAPS: dict[str, tuple[str, ...]] = {
    "온실": ("온실가스",),
    "발효": ("증발효과",),
}


def _occurrences(term: str, text: str) -> int:
    """힌트 등장 횟수. 더 긴 낱말에 삼켜진 건 빼고 센다."""
    n = len(re.findall(re.escape(term), text))
    for trap in HINT_TRAPS.get(term, ()):
        n -= len(re.findall(re.escape(trap), text))
    return max(n, 0)


@dataclass
class SectorVote:
    sector: str
    score: float
    matched: list[str] = field(default_factory=list)


@dataclass
class Classification:
    sector: str
    confidence: float
    needs_review: bool
    method: str
    votes: list[SectorVote] = field(default_factory=list)
    reason: str = ""

    def to_dict(self, lang: str = "ko") -> dict:
        p = taxonomy.get(self.sector)
        return {
            "sector": self.sector,
            "sector_name": taxonomy.sector_name(self.sector, lang),
            "ksic": p.ksic,
            "confidence": round(self.confidence, 3),
            "needs_review": self.needs_review,
            "method": self.method,
            "reason": self.reason,
            "unit_basis": p.unit_basis_en if lang == "en" else p.unit_basis,
            "votes": [
                {
                    "sector": v.sector,
                    "sector_name": taxonomy.sector_name(v.sector, lang),
                    "score": round(v.score, 2),
                    "matched": v.matched[:8],
                }
                for v in self.votes[:5]
            ],
        }


def _score(text: str) -> list[SectorVote]:
    """어휘 규칙 점수.

    업종을 가르지 못하는 말(`GENERIC_UTILITY`)은 아예 세지 않고, 더 긴 낱말에
    삼켜진 오탐(`HINT_TRAPS`)도 뺀다. 이 둘이 없으면 유틸리티 설비 언급량이
    공정 어휘를 압도해 업종이 뒤집힌다.

    등장 횟수의 **제곱근**을 쓴다 — 한 단어가 100번 나와도, 다른 어휘 10종이 한 번씩
    나온 쪽이 이겨야 한다. 머리말·꼬리말에 반복되는 한 단어로 업종이 뒤집히면 안 된다.
    """
    votes: list[SectorVote] = []
    for code, prof in taxonomy.SECTORS.items():
        if not prof.hints:
            continue
        total, matched = 0.0, []
        counted: set[str] = set()
        for h in prof.hints:
            if h in GENERIC_UTILITY:
                continue
            n = _occurrences(h, text)
            if n:
                total += n ** 0.5
                matched.append(f"{h}×{n}")
                counted.add(h)
        # 주요 설비명도 약한 신호로 센다. 다만 hints 에 이미 있는 말은 다시 세지
        # 않는다 — 같은 '냉동기' 를 두 번 세면 그 업종만 점수가 부풀어 오른다.
        for eq in prof.key_equipment:
            if eq in GENERIC_UTILITY or eq in counted:
                continue
            n = _occurrences(eq, text)
            if n:
                total += 0.4 * (n ** 0.5)
                matched.append(f"{eq}×{n}")
        if total > 0:
            votes.append(SectorVote(sector=code, score=total, matched=matched))
    votes.sort(key=lambda v: (-v.score, v.sector))
    return votes


def classify_text(text: str) -> Classification:
    """규칙만으로 분류. LLM 없이 동작하는 기준선 — 망분리 환경에서도 돈다."""
    votes = _score(text)
    if not votes or votes[0].score < MIN_SCORE:
        return Classification(
            sector=taxonomy.UNCLASSIFIED, confidence=0.0, needs_review=True,
            method="fallback", votes=votes,
            reason=f"업종 어휘 점수가 임계값({MIN_SCORE}) 미만이다. 사람이 지정해야 한다.",
        )

    top = votes[0]
    second = votes[1].score if len(votes) > 1 else 0.0
    total = sum(v.score for v in votes) or 1.0
    confidence = top.score / total
    margin = (top.score - second) / top.score if top.score else 0.0

    if margin < MARGIN_THRESHOLD:
        runner = votes[1].sector if len(votes) > 1 else taxonomy.UNCLASSIFIED
        return Classification(
            sector=top.sector, confidence=confidence, needs_review=True, method="rule",
            votes=votes,
            reason=(
                f"1위 {taxonomy.get(top.sector).name}({top.score:.1f})와 "
                f"2위 {taxonomy.get(runner).name}({second:.1f})의 격차가 "
                f"{margin:.0%}로 임계값({MARGIN_THRESHOLD:.0%}) 미만이다. 판단 유보."
            ),
        )

    return Classification(
        sector=top.sector, confidence=confidence, needs_review=False, method="rule",
        votes=votes,
        reason=(
            f"{taxonomy.get(top.sector).name} 어휘 {len(top.matched)}종 일치, "
            f"2위 대비 격차 {margin:.0%}."
        ),
    )


def manual(sector: str) -> Classification:
    """사람이 업종을 지정한 경우. 룰의 판단을 덮어쓰지만 그 사실을 기록한다."""
    taxonomy.get(sector)  # 닫힌 집합 밖이면 여기서 막는다
    return Classification(
        sector=sector, confidence=1.0, needs_review=False, method="manual",
        reason="사람이 직접 지정",
    )


def classify_document(doc) -> Classification:
    """ParsedDocument 를 분류한다. 표의 셀 텍스트도 신호로 쓴다 —
    설비명은 본문보다 표에 더 정확하게 적혀 있다."""
    return classify_text(doc.searchable_text)


# --------------------------------------------------------------------------- #
# 필수지표 커버리지 — "업종을 알면 무엇이 빠졌는지 물을 수 있다"
# --------------------------------------------------------------------------- #
def metric_coverage(doc, sector: str, lang: str = "ko") -> dict:
    """업종 프로파일의 required_metrics 가 문서에 실제로 있는지 점검.

    `llmwiki/compliance/analysis.py` 의 커버리지 갭과 같은 것이다 — 통제가 연결되지
    않은 의무를 찾듯, 진단서에 빠진 필수지표를 찾는다. 둘 다 그래프가 있어야 셀 수
    있는 숫자다.
    """
    prof = taxonomy.get(sector)
    haystack = doc.searchable_text

    present, missing = [], []
    for m in prof.required_metrics:
        pats = taxonomy.METRIC_PATTERNS.get(m, ())
        hit = next((p for p in pats if p in haystack), None)
        entry = {"code": m, "label": taxonomy.metric_label(m, lang), "evidence": hit or None}
        (present if hit else missing).append(entry)

    n = len(prof.required_metrics) or 1
    return {
        "sector": sector,
        "sector_name": taxonomy.sector_name(sector, lang),
        "unit_basis": prof.unit_basis_en if lang == "en" else prof.unit_basis,
        "required": n,
        "present": present,
        "missing": missing,
        "coverage": round(len(present) / n, 3),
    }
