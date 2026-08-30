"""구성 검토 (L3 확장) — 서식이 요구하는 절이 작업물에 실제로 있는가.

**필수 절 목록을 사람이 따로 만들지 않는다.** 회사가 이미 배포한 서식(별첨01~15)이
그 자체로 요구사항이라, 서식 문서를 파싱해 절 골격을 뽑으면 그것이 곧 체크리스트다.
체크리스트를 손으로 옮겨 적으면 서식이 개정될 때마다 낡는다 — 이 제품이 풀려는
문제와 똑같은 실패다.

여기서 하는 것은 **내용 평가가 아니다.** "위험평가가 충실한가" 는 묻지 않는다.
묻는 것은 둘뿐이다.

    요구된 절이 있는가 · 서식의 자리표시자가 그대로 남아 있지 않은가

둘 다 결정론적으로 답할 수 있고, 둘 다 사람이 세느라 시간을 버리던 것이다.
내용의 적정성은 여전히 사람 몫이고 판정 엔진은 그것을 판단 유보로 넘긴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .docparse import ParsedDoc, Section, parse

#: 서식에 남아 있는 채우지 않은 자리. 실제 별첨 서식에서 세어 보고 고른 것들이다.
#: '예시)' 처럼 서식이 안내문으로 쓰는 표현도 작업물에 그대로 남아 있으면
#: 그 절을 채우지 않았다는 뜻이다.
PLACEHOLDER_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"[…]{1,}", "말줄임표만 남음"),
    (r"\.{3,}", "말줄임표만 남음"),
    (r"[OＯ]{3,}", "OOO"),
    (r"[XＸ]{3,}", "XXX"),
    (r"YYYY[.\s-]*MM[.\s-]*DD", "날짜 서식 미기입"),
    (r"YYYY\.\s*MM\.\s*DD", "날짜 서식 미기입"),
    (r"\(?\s*예시\s*\)", "예시 안내문 잔존"),
    (r"내용을?\s*입력", "입력 안내문 잔존"),
    (r"여기에\s*입력", "입력 안내문 잔존"),
    (r"기재\s*(?:하시오|바랍니다|요망)", "기재 안내문 잔존"),
)

_PLACEHOLDER_RE = [(re.compile(p), why) for p, why in PLACEHOLDER_PATTERNS]

#: 서식의 표지·이력처럼 내용 검토 대상이 아닌 절
SKIP_TITLES = ("표지", "제개정이력", "제/개정 이력", "문서개요", "작성/검토자", "reference")


@dataclass
class RequiredSection:
    """서식이 요구하는 절 하나."""

    label: str
    level: int
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "level": self.level, "path": self.path}


@dataclass
class SectionReport:
    """작업물 구성 검토 결과. 판정이 아니라 사실의 나열이다."""

    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    placeholders: list[dict[str, Any]] = field(default_factory=list)
    empty_sections: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.placeholders and not self.empty_sections

    @property
    def need(self) -> int:
        return len(self.present) + len(self.missing)

    def to_dict(self) -> dict[str, Any]:
        return {
            "present": self.present, "missing": self.missing,
            "placeholders": self.placeholders, "empty_sections": self.empty_sections,
            "ok": self.ok,
        }


# --------------------------------------------------------------------------- #
# 서식 → 필수 절
# --------------------------------------------------------------------------- #
def required_sections(
    doc: ParsedDoc, *, max_level: int = 2, skip_annex: bool = False
) -> list[RequiredSection]:
    """서식 문서의 절 골격을 필수 절 목록으로.

    max_level 아래(가.·나. 같은 세부 항목)는 빼는 것이 기본이다. 세부까지 강제하면
    작업물이 조금만 달라도 미충족이 쏟아지고, 그러면 심사자가 결과를 안 믿게 된다.
    """
    out: list[RequiredSection] = []
    seen: set[str] = set()
    for s in doc.sections:
        if s.level > max_level:
            continue
        if _is_skippable(s):
            continue
        if skip_annex and _is_annex(s):
            continue
        key = _norm(s.label)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(RequiredSection(label=s.label, level=s.level, path=s.path))
    return out


def required_from_file(path: str | Path, **kwargs: Any) -> list[RequiredSection]:
    return required_sections(parse(path), **kwargs)


def _is_skippable(s: Section) -> bool:
    flat = _norm(s.label)
    return any(_norm(t) in flat for t in SKIP_TITLES)


def _is_annex(s: Section) -> bool:
    return bool(re.match(r"^(붙임|별첨|부록)", s.number.strip()))


# --------------------------------------------------------------------------- #
# 작업물 검토
# --------------------------------------------------------------------------- #
def review(
    work: ParsedDoc, required: list[RequiredSection] | list[str], *,
    check_placeholders: bool = True, min_body_chars: int = 12,
) -> SectionReport:
    """작업물이 요구된 절을 갖췄는지. 내용의 질은 보지 않는다."""
    report = SectionReport()
    labels = [r if isinstance(r, str) else r.label for r in required]
    have = {_norm(s.label): s for s in work.sections}

    for label in labels:
        matched = _match(label, have)
        if matched is None:
            report.missing.append(label)
            continue
        report.present.append(label)
        body = work.text[matched.start:matched.end]
        # 머리글줄을 뺀 알맹이가 사실상 비어 있으면 절만 남기고 안 쓴 것이다
        if len(_norm(body)) - len(_norm(matched.label)) < min_body_chars:
            report.empty_sections.append(label)

    if check_placeholders:
        report.placeholders = find_placeholders(work)
    return report


def _match(label: str, have: dict[str, Section]) -> Section | None:
    """절 제목 대조. 공백을 무시하고, 한쪽이 다른 쪽을 담고 있으면 같은 절로 본다.

    작업자는 서식의 제목을 조금씩 고쳐 쓴다("1. AI 서비스 개요" → "1. 서비스 개요").
    완전 일치를 요구하면 실제 문서에서는 거의 다 미충족이 된다.
    """
    want = _norm(label)
    if want in have:
        return have[want]
    for key, section in have.items():
        if want and (want in key or key in want):
            return section
    # 번호를 떼고 제목만으로 한 번 더. 양쪽 다 본다 —
    # 서식의 "1. AI 서비스 개요" 를 작업자가 "1. 서비스 개요" 로 줄여 쓰는 쪽이
    # 늘려 쓰는 쪽만큼 흔하다. 짧은 제목은 우연히 겹치므로 길이로 막는다.
    bare = _strip_number(want)
    if len(bare) >= 4:
        for key, section in have.items():
            other = _strip_number(key)
            if len(other) >= 4 and (bare in other or other in bare):
                return section
    return None


def find_placeholders(doc: ParsedDoc) -> list[dict[str, Any]]:
    """채우지 않은 자리를 찾는다. 위치를 함께 돌려줘 근거 스팬으로 쓸 수 있게 한다."""
    out: list[dict[str, Any]] = []
    for pattern, why in _PLACEHOLDER_RE:
        for m in pattern.finditer(doc.text):
            line_start = doc.text.rfind("\n", 0, m.start()) + 1
            line_end = doc.text.find("\n", m.end())
            line_end = len(doc.text) if line_end < 0 else line_end
            out.append({
                "why": why,
                "quote": doc.text[line_start:line_end].strip()[:120],
                "start": line_start,
                "end": line_end,
                "section": _section_at(doc, m.start()),
            })
            if len(out) >= 50:
                return out
    return out


def _section_at(doc: ParsedDoc, offset: int) -> str:
    for s in doc.sections:
        if s.start <= offset < s.end:
            return s.label
    return ""


# --------------------------------------------------------------------------- #
def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def _strip_number(text: str) -> str:
    return re.sub(r"^[0-9ivxIVX가-힣]{1,4}[.)]", "", text).strip()
