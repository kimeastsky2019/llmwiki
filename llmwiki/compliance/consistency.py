"""문서 간 정합성 (L5) — 같은 값을 말하는 문서끼리 값이 다른가.

기획서에는 임계치 0.75 라고 써 놓고 검증결과서에는 0.70 이라고 적혀 있는 것.
사람이 제일 못 잡고 감리에서 제일 먼저 걸리는 종류다. 문서가 여러 개로 쪼개져
있고 작성 시점이 다르면 필연적으로 생긴다.

**이것은 품질 판단이 아니라 대조다.** "어느 쪽이 옳은가" 는 묻지 않는다.
"두 문서가 다른 말을 하고 있다" 는 사실만 내놓고, 어느 쪽이 맞는지는 사람이 정한다.
그래서 LLM 이 필요 없고, 그래서 결정론적이다.

값을 뽑는 방식
-------------
업무 문서의 값은 대부분 `구분 | 내용` 표 안에 있다. 파서가 표를 `| a | b |` 로
펴 두었으므로, 각 줄을 (이름, 값) 쌍으로 읽고 이름을 정규화해 맞춘다.
문장 속 `AUC 0.82` 같은 표기도 함께 줍는다.

한계는 분명히 해 둔다. 이름이 서로 다르게 적힌 값(`임계치` vs `기준값`)은 맞추지
못한다. 별칭은 `aliases` 로 사람이 등록한다 — 추측으로 맞추면 없는 불일치를
만들어 내고, 그 편이 놓치는 것보다 나쁘다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .docparse import ParsedDoc

#: 값으로 볼 것 — 숫자(단위 포함), 날짜, 예/아니오
_NUMBER_RE = re.compile(r"^[-+]?\d[\d,]*(?:\.\d+)?\s*(%|퍼센트|건|명|일|개월|년|원)?$")
_DATE_RE = re.compile(r"^\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}\.?$")
_YESNO = {"예": "Y", "아니오": "N", "y": "Y", "n": "N", "해당": "Y", "미해당": "N",
          "해당없음": "N", "yes": "Y", "no": "N", "o": "Y", "x": "N"}

#: 문장 안에 박힌 `이름 값` 표기. 이름은 한글·영문 토큰, 값은 숫자다.
_INLINE_RE = re.compile(
    r"([A-Za-z가-힣][A-Za-z가-힣_ ]{1,18}?)\s*(?:은|는|이|가|:|=)?\s*"
    r"([-+]?\d[\d,]*(?:\.\d+)?\s*%?)(?:\s|$|,|\.)"
)

#: 이름이 이것들 중 하나면 값으로 보지 않는다 (표의 머리글·안내문)
_NOISE = {
    "구분", "내용", "항목", "비고", "no", "번호", "순번", "작성자", "검토자",
    # 문서의 뼈대를 가리키는 말 — 값처럼 생겼지만 값이 아니다
    "붙임", "별첨", "부록", "장", "절", "조", "항", "호", "목차", "페이지", "쪽",
    "버전", "version", "표", "그림", "단계",
}


@dataclass
class Claim:
    """한 문서가 말하는 값 하나."""

    key: str            # 정규화한 이름
    label: str          # 문서에 적힌 그대로
    value: str          # 정규화한 값
    raw: str            # 원문 표기
    doc_id: str
    section: str
    start: int
    end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "label": self.label, "value": self.value,
            "raw": self.raw, "doc_id": self.doc_id, "section": self.section,
            "start": self.start, "end": self.end,
        }


@dataclass
class Conflict:
    """같은 이름에 서로 다른 값을 말하는 문서들."""

    key: str
    values: dict[str, list[Claim]] = field(default_factory=dict)

    @property
    def documents(self) -> list[str]:
        return sorted({c.doc_id for group in self.values.values() for c in group})

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "documents": self.documents,
            "values": {
                value: [c.to_dict() for c in group]
                for value, group in sorted(self.values.items())
            },
        }

    def summary(self) -> str:
        parts = [
            f"{value} ({', '.join(sorted({c.doc_id for c in group}))})"
            for value, group in sorted(self.values.items())
        ]
        return f"{self.key}: " + " ≠ ".join(parts)


# --------------------------------------------------------------------------- #
def extract_claims(doc: ParsedDoc, *, aliases: dict[str, str] | None = None) -> list[Claim]:
    """문서에서 (이름, 값) 쌍을 뽑는다. 표가 주 경로다."""
    aliases = {normalize_key(k): v for k, v in (aliases or {}).items()}
    # 절 머리글은 구조이지 주장이 아니다. "붙임1." 을 (붙임=1) 로 읽으면
    # 문서마다 붙임 번호가 다르다는 이유로 없는 불일치가 만들어진다.
    headings = {s.start for s in doc.sections}
    claims: list[Claim] = []
    pos = 0
    for line in doc.text.split("\n"):
        start = pos
        pos += len(line) + 1
        stripped = line.strip()
        if not stripped or start in headings:
            continue
        if stripped.startswith("|"):
            claims.extend(_from_table_line(doc, stripped, start, aliases))
        else:
            claims.extend(_from_sentence(doc, line, start, aliases))
    return claims


def _from_table_line(
    doc: ParsedDoc, line: str, start: int, aliases: dict[str, str]
) -> list[Claim]:
    cells = [c.strip() for c in line.strip("|").split("|")]
    cells = [c for c in cells if c]
    if len(cells) < 2:
        return []
    out: list[Claim] = []
    # `구분 | 내용` 두 칸 표와 `이름 | 값 | 비고` 여러 칸 표를 함께 다룬다
    label = cells[0]
    for cell in cells[1:]:
        value = normalize_value(cell)
        if value is None:
            continue
        key = aliases.get(normalize_key(label), normalize_key(label))
        if not key or key in _NOISE:
            continue
        offset = start + line.find(cell)
        out.append(Claim(key, label, value, cell, doc.doc_id,
                         _section_at(doc, start), offset, offset + len(cell)))
        break   # 한 행에서 값 하나만 — 비고 칸까지 값으로 세면 잡음이 늘어난다
    return out


def _from_sentence(
    doc: ParsedDoc, line: str, start: int, aliases: dict[str, str]
) -> list[Claim]:
    out: list[Claim] = []
    for m in _INLINE_RE.finditer(line):
        label = m.group(1).strip()
        raw = m.group(2).strip()
        key = aliases.get(normalize_key(label), normalize_key(label))
        if not key or key in _NOISE or len(key) < 2:
            continue
        value = normalize_value(raw)
        if value is None:
            continue
        offset = start + m.start(2)
        out.append(Claim(key, label, value, raw, doc.doc_id,
                         _section_at(doc, start), offset, offset + len(raw)))
    return out


def compare(
    docs: Iterable[ParsedDoc], *, aliases: dict[str, str] | None = None,
    min_documents: int = 2,
) -> list[Conflict]:
    """여러 문서를 대조해 불일치를 찾는다.

    같은 문서 안에서 값이 여러 번 나오는 것은 불일치로 세지 않는다 — 표와 본문에
    같은 값을 반복해 적는 것이 정상이고, 문서 안의 중복은 다른 문제다.
    """
    by_key: dict[str, list[Claim]] = {}
    for doc in docs:
        for claim in extract_claims(doc, aliases=aliases):
            by_key.setdefault(claim.key, []).append(claim)

    conflicts: list[Conflict] = []
    for key, claims in sorted(by_key.items()):
        docs_seen = {c.doc_id for c in claims}
        if len(docs_seen) < min_documents:
            continue
        grouped: dict[str, list[Claim]] = {}
        for c in claims:
            grouped.setdefault(c.value, []).append(c)
        if len(grouped) < 2:
            continue
        # 값이 갈리되, 서로 다른 문서가 다른 값을 말할 때만 불일치다
        value_docs = {v: {c.doc_id for c in g} for v, g in grouped.items()}
        if len({frozenset(d) for d in value_docs.values()}) < 2:
            continue
        conflicts.append(Conflict(key=key, values=grouped))
    return conflicts


def report(conflicts: list[Conflict]) -> dict[str, Any]:
    return {
        "conflicts": [c.to_dict() for c in conflicts],
        "summary": {
            "keys": len(conflicts),
            "documents": sorted({d for c in conflicts for d in c.documents}),
        },
    }


# --------------------------------------------------------------------------- #
def normalize_key(text: str) -> str:
    out = re.sub(r"[\s()\[\]{}·:：]+", "", text).lower()
    out = re.sub(r"^[0-9ivx가-힣]{1,3}[.)]", "", out)
    return out.strip("-_.")[:40]


def normalize_value(text: str) -> str | None:
    """값으로 볼 수 있으면 정규화해 돌려주고, 아니면 None.

    자유 서술은 대조 대상이 아니다. 문장은 표현이 달라도 같은 뜻일 수 있어서
    다르다고 말하는 순간 거짓 경보가 쏟아진다. 숫자·날짜·예아니오만 본다.
    """
    raw = text.strip()
    if not raw or len(raw) > 24:
        return None
    lowered = raw.lower().rstrip(".")
    if lowered in _YESNO:
        return _YESNO[lowered]
    if _DATE_RE.match(raw):
        digits = re.findall(r"\d+", raw)
        if len(digits) == 3:
            return f"{int(digits[0]):04d}-{int(digits[1]):02d}-{int(digits[2]):02d}"
    if _NUMBER_RE.match(raw):
        body = re.sub(r"[,\s]", "", raw)
        unit = ""
        m = re.search(r"(%|퍼센트|건|명|일|개월|년|원)$", body)
        if m:
            unit = "%" if m.group(1) in ("%", "퍼센트") else m.group(1)
            body = body[: m.start()]
        try:
            number = float(body)
        except ValueError:
            return None
        # 0.750 과 0.75 는 같은 값이다
        text_value = f"{number:g}"
        return f"{text_value}{unit}"
    return None


def _section_at(doc: ParsedDoc, offset: int) -> str:
    for s in doc.sections:
        if s.start <= offset < s.end:
            return s.label
    return ""
