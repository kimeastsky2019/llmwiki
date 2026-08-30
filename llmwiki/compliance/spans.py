"""근거 스팬과 인용 강도 — LLM 환각이 승인 그래프에 들어오지 못하게 막는 두 겹.

첫 겹: **스팬이 실재하는가**
    제안에 붙은 근거가 `문서ID + 문자 오프셋 + 인용문` 이므로,
    `문서[start:end] == 인용문` 인지 기계적으로 대조할 수 있다.
    모델이 그럴듯한 문장을 지어내면 오프셋이 맞지 않아 여기서 걸린다.
    이것이 "근거 없는 사실 금지" 를 실제로 강제하는 지점이다.

둘째 겹: **주장이 근거보다 강하지 않은가**
    조문이 "노력하여야 한다"(권고) 인데 제안이 "필수 의무" 라고 말하면,
    문장은 인용했지만 주장이 근거를 넘어선 것이다. 규제 문서에서 이 차이는
    준수 여부를 뒤집는다. 어미로 강도를 재고 `주장 강도 ≤ 근거 강도` 를 요구한다.

강도 판정은 룰이지 모델이 아니다. 사전을 늘릴 수는 있어도 판단은 결정론적이다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

# --- 인용 강도 ------------------------------------------------------------- #
FORCE_INFO = 0      # 사실 서술
FORCE_MAY = 1       # 재량
FORCE_SHOULD = 2    # 권고 · 노력 의무
FORCE_MUST = 3      # 필수 의무 · 금지

FORCE_NAMES: dict[int, str] = {
    FORCE_INFO: "informative", FORCE_MAY: "discretionary",
    FORCE_SHOULD: "recommended", FORCE_MUST: "mandatory",
}

#: 완화 어미. "노력하여야 한다" 는 "하여야 한다" 를 포함하므로 먼저 걷어낸다.
#: 이 순서를 뒤집으면 권고가 전부 필수로 읽힌다.
_SOFTENERS: tuple[str, ...] = (
    "노력하여야 한다", "노력하여야 하며", "노력해야 한다", "노력하여야",
    "노력한다", "노력하도록", "지향한다",
)

#: `-아야/-어야/-여야 한다` 는 '하다' 에만 붙는 게 아니다.
#: "승인을 **받아야 한다**", "기준을 **지켜야 한다**", "요건을 **갖추어야 한다**" —
#: 어간이 무엇이든 앞 음절이 '야' 로 끝나고 뒤에 '한다' 류가 오면 강제 의무다.
#: 문자열 목록으로만 두면 '하여야/해야' 밖의 동사를 전부 놓친다 (실제로 놓쳤다).
_MUST_RE = re.compile(r"[가-힣]야\s*(?:한다|하며|하고|하는|합니다|할|함)")

_PATTERNS: tuple[tuple[str, int], ...] = (
    # 필수
    ("하여야 한다", FORCE_MUST), ("해야 한다", FORCE_MUST),
    ("하여야 하며", FORCE_MUST), ("해야 하며", FORCE_MUST),
    ("하여야 함", FORCE_MUST), ("아니 된다", FORCE_MUST),
    ("아니된다", FORCE_MUST), ("하여서는 아니", FORCE_MUST),
    ("금지한다", FORCE_MUST), ("금지된다", FORCE_MUST),
    ("의무가 있다", FORCE_MUST), ("필수적으로", FORCE_MUST),
    ("반드시", FORCE_MUST), ("required", FORCE_MUST), ("must ", FORCE_MUST),
    ("shall ", FORCE_MUST),
    # 권고
    ("권고한다", FORCE_SHOULD), ("권고된다", FORCE_SHOULD), ("권고사항", FORCE_SHOULD),
    ("바람직하다", FORCE_SHOULD), ("권장한다", FORCE_SHOULD), ("권장된다", FORCE_SHOULD),
    ("should ", FORCE_SHOULD), ("recommended", FORCE_SHOULD),
    # 재량
    ("할 수 있다", FORCE_MAY), ("수 있다", FORCE_MAY), ("may ", FORCE_MAY),
    ("optional", FORCE_MAY),
)

#: 제안된 사실이 주장하는 강도. 여기 없는 종류는 검증 대상이 아니다.
_CLAIM_FORCE: dict[str, int] = {"mandatory": FORCE_MUST, "recommended": FORCE_SHOULD}


@dataclass
class Span:
    """원문 스팬 — 문서ID + 섹션 + 문자 오프셋 + 인용문.

    L0 파서가 부여하는 불변 앵커이며, 모든 문서 유래 사실이 이것을 갖는다.
    """

    doc_id: str
    start: int
    end: int
    quote: str
    section: str = ""
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v not in ("", None)}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Span":
        return cls(
            doc_id=str(raw.get("doc_id", "")),
            start=int(raw.get("start", 0)),
            end=int(raw.get("end", 0)),
            quote=str(raw.get("quote", "")),
            section=str(raw.get("section", "")),
            sha256=str(raw.get("sha256", "")),
        )

    @classmethod
    def of(cls, doc_id: str, text: str, start: int, end: int, section: str = "") -> "Span":
        """원문에서 잘라 스팬을 만든다 — 인용문이 원문과 어긋날 수 없는 유일한 방법."""
        quote = text[start:end]
        return cls(doc_id=doc_id, start=start, end=end, quote=quote,
                   section=section, sha256=digest(quote))

    @property
    def force(self) -> int:
        return force_of(self.quote)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def force_of(text: str) -> int:
    """문장의 강제력을 잰다. 완화 어미를 먼저 걷어낸 뒤 최댓값을 취한다."""
    if not text:
        return FORCE_INFO
    softened = text
    found_soft = False
    for pattern in _SOFTENERS:
        if pattern in softened:
            softened = softened.replace(pattern, " ")
            found_soft = True
    best = FORCE_SHOULD if found_soft else FORCE_INFO
    if _MUST_RE.search(softened):
        best = FORCE_MUST
    lowered = softened.lower()
    for pattern, force in _PATTERNS:
        needle = pattern if not pattern.isascii() else pattern.lower()
        if needle in lowered:
            best = max(best, force)
    return best


def claim_force_of(props: dict[str, Any]) -> tuple[int, str] | None:
    """제안된 사실이 주장하는 강도와 그 근거가 된 속성. 검증 대상이 아니면 None.

    속성을 함께 돌려주는 이유가 있다. `level` 은 규제 문서를 읽고 "이건 필수다"
    라고 말하는 것이라 근거 문장이 반드시 있어야 한다. 반면 `required_yn` 은
    조직이 "우리는 이 증적을 요구한다" 고 정한 것이라 문서 인용이 아니다 —
    근거를 달았다면 그 강도를 검사하되, 없다고 해서 틀린 것은 아니다.
    """
    level = props.get("level")
    if isinstance(level, str) and level in _CLAIM_FORCE:
        return _CLAIM_FORCE[level], "level"
    if props.get("required_yn") is True:
        return FORCE_MUST, "required_yn"
    return None


# --- 검증 ------------------------------------------------------------------ #
@dataclass
class SpanIssue:
    code: str
    message: str


@dataclass
class SpanCheck:
    issues: list[SpanIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def fail(self, code: str, message: str) -> None:
        self.issues.append(SpanIssue(code, message))


def verify_span(span: Span, documents: dict[str, str] | None = None) -> SpanCheck:
    """스팬이 실제 원문을 가리키는지 대조한다.

    documents 를 주지 않으면 형태만 본다 — 원문 없이 오프셋의 진위를 확인할 수는
    없으므로, 그 경우 "대조하지 않았다" 는 사실을 경고로 남기지 않고 통과시킨다.
    대조 책임은 원문을 쥔 쪽(L4 검증)에 있다.
    """
    check = SpanCheck()
    if not span.doc_id:
        check.fail("span.doc_id", "문서 ID 가 없다")
    if span.end <= span.start:
        check.fail("span.range", f"스팬 범위가 비었다 ({span.start}~{span.end})")
    if not span.quote.strip():
        check.fail("span.quote", "인용문이 비었다")
    if span.sha256 and span.quote and span.sha256 != digest(span.quote):
        check.fail("span.digest", "인용문 해시가 맞지 않는다")

    if documents is None:
        return check
    text = documents.get(span.doc_id)
    if text is None:
        check.fail("span.doc", f"원문을 찾을 수 없다: {span.doc_id}")
        return check
    if span.end > len(text):
        check.fail("span.range", f"스팬이 원문 길이({len(text)})를 넘는다")
        return check
    actual = text[span.start:span.end]
    if actual != span.quote:
        check.fail(
            "span.mismatch",
            f"{span.doc_id}[{span.start}:{span.end}] 원문과 인용문이 다르다 "
            f"— 원문 {actual[:30]!r} / 인용 {span.quote[:30]!r}",
        )
    return check


def check_citation_force(
    props: dict[str, Any], spans: list[Span], *, label: str = ""
) -> SpanCheck:
    """주장 강도 ≤ 근거 강도. 넘어서면 실패다."""
    check = SpanCheck()
    claimed = claim_force_of(props)
    if claimed is None:
        return check
    claim, origin = claimed
    if not spans:
        if origin == "level":
            check.fail("citation.missing",
                       f"{label}: 문서에서 강제력을 주장하는데 근거 스팬이 없다")
        return check
    evidence = max(span.force for span in spans)
    if claim > evidence:
        check.fail(
            "citation.force",
            f"{label}: claim is {FORCE_NAMES[claim]} but the quoted text is only "
            f"{FORCE_NAMES[evidence]} — quote: {spans[0].quote[:40]!r}",
        )
    return check


def locate_quote(text: str, quote: str) -> tuple[int, int] | None:
    """원문에서 인용문의 위치를 찾는다. 못 찾으면 None.

    글자 그대로 찾아보고, 안 되면 **공백만 무시하고** 다시 찾는다.
    법령 원문은 한 문장이 여러 줄에 걸쳐 접혀 있는데 모델은 그것을 한 줄로 옮긴다.
    이 차이로 정당한 인용을 버리면 실제 문서에서는 거의 아무것도 통과하지 못한다
    (배포해서 Grok 을 물렸을 때 정확한 인용 5건이 전부 이것 때문에 떨어졌다).

    느슨해지는 것은 **찾는 방법**뿐이고 보장은 그대로다. 반환하는 것은 원문의
    오프셋이고, 호출 측은 그 구간을 원문에서 다시 잘라 스팬을 만든다. 저장되는
    인용문은 언제나 원문에서 온 것이지 모델이 준 문자열이 아니다. 지어낸 문장은
    정규화해도 원문에 없으므로 여전히 여기서 죽는다.
    """
    if not quote.strip():
        return None
    direct = text.find(quote)
    if direct >= 0:
        return direct, direct + len(quote)

    # 공백을 하나로 접은 사본과, 그 위치를 원문 위치로 되돌리는 색인
    flat: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            if flat and flat[-1] == " ":
                continue
            flat.append(" ")
        else:
            flat.append(ch)
        origin.append(i)

    needle = " ".join(quote.split())
    pos = "".join(flat).find(needle)
    if pos < 0:
        return None
    return origin[pos], origin[pos + len(needle) - 1] + 1


def parse_spans(raw: Any) -> list[Span]:
    """props/엣지에 실려 온 스팬 목록을 Span 으로."""
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    out: list[Span] = []
    for item in raw:
        if isinstance(item, Span):
            out.append(item)
        elif isinstance(item, dict):
            out.append(Span.from_dict(item))
    return out


# --- 조문 분할 (L0) --------------------------------------------------------- #
#: "제12조", "제12조의2", "제12조(목적)" 을 모두 잡는다.
ARTICLE_RE = re.compile(r"제\s*(\d+)\s*조(?:\s*의\s*(\d+))?")


def split_articles(text: str) -> list[dict[str, Any]]:
    """법령 원문을 조문 단위로 자르고 각 조문에 문자 오프셋을 붙인다.

    LLM 을 쓰지 않는다. 조문 번호는 반환하되 **식별자로 쓰지 않는다** —
    호출 측이 UUID 앵커를 부여하고 번호는 속성으로 넣는다.
    """
    marks = list(ARTICLE_RE.finditer(text))
    out: list[dict[str, Any]] = []
    for i, m in enumerate(marks):
        start = m.start()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[start:end].strip()
        number = f"제{m.group(1)}조" + (f"의{m.group(2)}" if m.group(2) else "")
        title = ""
        head = text[m.end():end]
        if head.lstrip().startswith("("):
            inner = head.lstrip()
            close = inner.find(")")
            if close > 0:
                title = inner[1:close].strip()
        out.append({
            "number": number,
            "title": title,
            "text": body,
            "start": start,
            "end": start + len(text[start:end].rstrip()),
        })
    return out
