"""데이터 컨트랙트 — front-matter 없는 문서는 파이프라인에 진입하지 못한다 (P3).

컨트랙트는 "이 문서가 무엇이고, 어디서 왔고, 누가 책임지고, 어디까지 나갈 수 있는가"
를 기계가 읽을 수 있는 형태로 못 박는 것이다. 이게 없으면 세 가지가 무너진다.

* **출처 추적** — `source_span` 이 없으면 수치의 근거를 되짚을 수 없다.
* **접근 통제** — `acl` 이 없으면 고객사 설비 정보가 외부 API 로 나간다 (P5).
* **책임 소재** — `owner`/`status` 가 없으면 검토되지 않은 초안이 확정본처럼 인용된다.

`llmwiki/kb/taxonomy.py` 와 `llmwiki/compliance/ontology.py` 가 그랬듯 **집합은 닫혀
있다.** 여기 없는 타입·등급은 위키에 나올 수 없고, 새로 필요하면 먼저 이 파일을 고쳐야
한다. 순서를 강제하는 것이 핵심이다.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

CONTRACT_VERSION = "0.1.0"


@dataclass(frozen=True)
class PageType:
    name: str
    prefix: str
    directory: str
    ko: str
    en: str
    note: str = ""


#: 페이지 타입 닫힌 집합. 기획서 4.1 온톨로지 + 원문 대응 페이지(source).
#: prefix 는 stable_id 의 앞머리다 — ID 만 보고 타입을 알 수 있어야 링크가 안전하다.
PAGE_TYPES: dict[str, PageType] = {
    p.name: p
    for p in (
        PageType("source", "src", "sources", "원문", "Source",
                 note="원본 문서 1건에 1:1 대응하는 요약 페이지. 모든 인용의 출발점."),
        PageType("diagnosis", "dgn", "entities", "진단 건", "Diagnosis",
                 note="진단 프로젝트 1건. 사업장·설비·개선안을 묶는 허브."),
        PageType("facility", "fac", "entities", "사업장", "Facility"),
        PageType("equipment", "eqp", "entities", "설비", "Equipment"),
        PageType("vendor", "ven", "entities", "공급사", "Vendor"),
        PageType("measure", "ecm", "measures", "개선안(ECM)", "Measure",
                 note="재사용 자산의 핵심. 사업장이 달라도 패턴이 반복된다."),
        PageType("metric", "mtr", "metrics", "지표·원단위", "Metric"),
        PageType("regulation", "reg", "regulations", "법규·계수", "Regulation",
                 note="유효기간을 갖는다. 만료 임박은 lint 가 경고한다."),
        PageType("concept", "cpt", "concepts", "인사이트", "Concept",
                 note="질의 과정에서 발견된 패턴. 초안으로 태어나 검토로 승격된다."),
    )
}

TYPE_NAMES: tuple[str, ...] = tuple(PAGE_TYPES)
DIRECTORIES: tuple[str, ...] = tuple(dict.fromkeys(p.directory for p in PAGE_TYPES.values()))

#: 접근 등급. 순서가 곧 강도다 — 라우팅과 lint 가 이 순서로 판정한다.
ACL_LEVELS: tuple[str, ...] = ("public", "internal", "confidential", "restricted")

#: 사외(외부 API)로 내보낼 수 없는 등급. P5 의 집행 지점.
ACL_INTERNAL_ONLY: frozenset[str] = frozenset({"confidential", "restricted"})

STATUSES: tuple[str, ...] = ("draft", "reviewed", "deprecated")

DOMAINS: tuple[str, ...] = ("building", "industrial", "renewable")

#: 실측/문헌/추정/설계값. 구분하지 않으면 벤치마크가 오염된다 — 진단서 최다 오독 지점.
#: `llmwiki/kb/ontology.py` 의 근거 등급(derivation)과 다음처럼 대응한다.
#:
#:   measured   → measured    현장 계측기 실측
#:   documented → documented  청구서·명판·계약·법정계수
#:   assumed    → estimated   가정·카탈로그
#:   computed   → mixed       위 셋에서 계산된 값 (입력의 근거가 섞인다)
MEASUREMENT_BASES: tuple[str, ...] = (
    "measured", "documented", "estimated", "design", "mixed",
)

#: kb 그래프의 derivation 을 컨트랙트의 measurement_basis 로 옮기는 표.
#: 두 어휘를 각자 두면 같은 사실이 계층마다 다른 이름을 받는다.
BASIS_FROM_DERIVATION: dict[str, str] = {
    "measured": "measured",
    "documented": "documented",
    "assumed": "estimated",
    "computed": "mixed",
}

CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")

UNIT_SYSTEMS: tuple[str, ...] = ("SI", "KR")

#: front-matter 필수 필드. 하나라도 없으면 파이프라인 진입 금지.
REQUIRED_FIELDS: tuple[str, ...] = (
    "stable_id", "type", "version", "content_hash", "source_span",
    "acl", "provenance", "owner", "status",
    "domain", "unit_system", "measurement_basis", "confidence", "numeric_verified",
)

PROVENANCE_FIELDS: tuple[str, ...] = ("ingested_by", "ingested_at", "pipeline_version")

ID_RE = re.compile(r"^[a-z][a-z0-9]{1,4}-[a-z0-9]+(?:-[a-z0-9]+)*$")

WIKILINK_RE = re.compile(r"\[\[([^\[\]|]+?)(?:\|[^\[\]]*)?\]\]")


# --------------------------------------------------------------------------- #
# 검증 결과
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    code: str
    severity: str          # error | warning
    field: str
    message: str
    page: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ValidationResult:
    ok: bool
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
        }


# --------------------------------------------------------------------------- #
# 헬퍼
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def content_hash(body: str) -> str:
    """본문 해시. 원본이 바뀌었는지를 이 값으로 감지한다."""
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def type_of(stable_id: str) -> str | None:
    """ID 앞머리로 타입을 판정한다. 링크 대상의 타입을 파일을 열지 않고 알 수 있다."""
    prefix = (stable_id or "").split("-", 1)[0]
    for t in PAGE_TYPES.values():
        if t.prefix == prefix:
            return t.name
    return None


def directory_of(page_type: str) -> str:
    try:
        return PAGE_TYPES[page_type].directory
    except KeyError as exc:
        raise KeyError(f"정의되지 않은 페이지 타입이다: {page_type}") from exc


def acl_rank(acl: str) -> int:
    try:
        return ACL_LEVELS.index(acl)
    except ValueError as exc:
        raise KeyError(f"정의되지 않은 접근 등급이다: {acl}") from exc


def acl_allows_reference(source_acl: str, target_acl: str) -> bool:
    """낮은 등급 페이지가 높은 등급 페이지를 참조하면 위반이다.

    `public` 페이지가 `confidential` 페이지를 링크하면 그 링크 자체가 존재와 맥락을
    흘린다. 이 판정이 lint 에서 **배포 차단** 사유가 된다 (P5).
    """
    return acl_rank(target_acl) <= acl_rank(source_acl)


def links_in(body: str) -> list[str]:
    """본문의 위키 링크 `[[id]]` 목록. 중복은 제거하되 순서는 유지한다."""
    seen: dict[str, None] = {}
    for m in WIKILINK_RE.finditer(body or ""):
        seen.setdefault(m.group(1).strip(), None)
    return list(seen)


def slug(text: str, maxlen: int = 48) -> str:
    """ID 조각용 슬러그. 한글은 그대로 두지 않는다 — ID 는 ASCII 로만 만든다."""
    s = re.sub(r"[^\w\s-]", "", (text or "").lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:maxlen] or "unnamed"


# --------------------------------------------------------------------------- #
# front-matter 생성
# --------------------------------------------------------------------------- #
def new_front_matter(
    *,
    stable_id: str,
    page_type: str,
    body: str,
    source_span: list[dict[str, Any]],
    acl: str = "internal",
    owner: str = "energy-team",
    status: str = "draft",
    domain: str = "industrial",
    unit_system: str = "SI",
    measurement_basis: str = "documented",
    measurement_period: str = "",
    confidence: str = "medium",
    numeric_verified: bool = False,
    ingested_by: str = "rule-engine",
    pipeline_version: str = "v0.1.0",
    version: int = 1,
    tags: list[str] | None = None,
    related: list[str] | None = None,
    title: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """규격을 만족하는 front-matter 를 만든다. 여기를 거치지 않은 dict 는 신뢰하지 않는다."""
    fm: dict[str, Any] = {
        "stable_id": stable_id,
        "type": page_type,
        "title": title or stable_id,
        "version": version,
        "content_hash": content_hash(body),
        "source_span": source_span,
        "acl": acl,
        "provenance": {
            "ingested_by": ingested_by,
            "ingested_at": now_iso(),
            "pipeline_version": pipeline_version,
        },
        "owner": owner,
        "status": status,
        "domain": domain,
        "unit_system": unit_system,
        "measurement_basis": measurement_basis,
        "measurement_period": measurement_period,
        "confidence": confidence,
        "numeric_verified": numeric_verified,
        "tags": list(tags or []),
        "related": list(related or []),
    }
    if extra:
        fm.update(extra)
    return fm


# --------------------------------------------------------------------------- #
# 검증
# --------------------------------------------------------------------------- #
def validate(fm: dict[str, Any], body: str = "", *, page: str = "") -> ValidationResult:
    """front-matter 한 벌을 검증한다. 파일 시스템을 보지 않는다 (링크 무결성은 lint 몫)."""
    issues: list[Issue] = []

    def err(code: str, fld: str, msg: str) -> None:
        issues.append(Issue(code, "error", fld, msg, page))

    def warn(code: str, fld: str, msg: str) -> None:
        issues.append(Issue(code, "warning", fld, msg, page))

    for name in REQUIRED_FIELDS:
        if name not in fm or fm[name] in (None, ""):
            err("schema.missing_field", name, f"필수 필드가 없다: {name}")

    sid = str(fm.get("stable_id", ""))
    ptype = str(fm.get("type", ""))
    if sid and not ID_RE.match(sid):
        err("schema.bad_id", "stable_id",
            f"stable_id 형식이 아니다: {sid} (소문자·숫자·하이픈, 접두사-본문)")
    if ptype and ptype not in PAGE_TYPES:
        err("schema.bad_type", "type", f"정의되지 않은 타입이다: {ptype}")
    elif sid and ptype and type_of(sid) != ptype:
        err("schema.prefix_mismatch", "stable_id",
            f"ID 접두사가 타입과 다르다: {sid} vs {ptype}"
            f" (기대: {PAGE_TYPES[ptype].prefix}-…)")

    acl = str(fm.get("acl", ""))
    if acl and acl not in ACL_LEVELS:
        err("schema.bad_acl", "acl", f"정의되지 않은 접근 등급이다: {acl}")

    status = str(fm.get("status", ""))
    if status and status not in STATUSES:
        err("schema.bad_status", "status", f"정의되지 않은 상태다: {status}")

    domain = str(fm.get("domain", ""))
    if domain and domain not in DOMAINS:
        err("schema.bad_domain", "domain", f"정의되지 않은 도메인이다: {domain}")

    basis = str(fm.get("measurement_basis", ""))
    if basis and basis not in MEASUREMENT_BASES:
        # 근거 강도는 벤치마크 오염과 직결된다. 자유 문자열을 허용하면 실측과 설계값이
        # 같은 통계에 섞인다.
        err("schema.bad_basis", "measurement_basis",
            f"정의되지 않은 측정 근거다: {basis} (허용: {', '.join(MEASUREMENT_BASES)})")

    conf = str(fm.get("confidence", ""))
    if conf and conf not in CONFIDENCES:
        err("schema.bad_confidence", "confidence", f"정의되지 않은 신뢰도다: {conf}")

    if str(fm.get("unit_system", "")) not in UNIT_SYSTEMS:
        warn("schema.bad_unit_system", "unit_system",
             f"단위계 표기가 표준이 아니다: {fm.get('unit_system')}")

    spans = fm.get("source_span")
    if isinstance(spans, list):
        if not spans:
            err("schema.no_source_span", "source_span",
                "근거 스팬이 비어 있다 — 출처 없는 페이지는 인용될 수 없다")
        for i, span in enumerate(spans):
            if not isinstance(span, dict) or not span.get("doc"):
                err("schema.bad_source_span", f"source_span[{i}]",
                    "근거 스팬에 doc 이 없다")
    elif "source_span" in fm:
        err("schema.bad_source_span", "source_span", "source_span 은 목록이어야 한다")

    prov = fm.get("provenance")
    if isinstance(prov, dict):
        for name in PROVENANCE_FIELDS:
            if not prov.get(name):
                err("schema.bad_provenance", f"provenance.{name}",
                    f"provenance.{name} 이 비어 있다")
    elif "provenance" in fm:
        err("schema.bad_provenance", "provenance", "provenance 는 매핑이어야 한다")

    if not isinstance(fm.get("version"), int) or int(fm.get("version", 0)) < 1:
        err("schema.bad_version", "version", "version 은 1 이상의 정수여야 한다")

    if not isinstance(fm.get("numeric_verified"), bool):
        err("schema.bad_numeric_verified", "numeric_verified",
            "numeric_verified 는 참/거짓이어야 한다")

    if body:
        expected = content_hash(body)
        if fm.get("content_hash") and fm["content_hash"] != expected:
            warn("schema.stale_hash", "content_hash",
                 "본문이 바뀌었는데 content_hash 가 갱신되지 않았다")

    for name in ("tags", "related"):
        if name in fm and not isinstance(fm[name], list):
            err("schema.bad_list", name, f"{name} 은 목록이어야 한다")

    return ValidationResult(ok=not any(i.severity == "error" for i in issues), issues=issues)


def schema_dict() -> dict[str, Any]:
    """화면·CLI 가 닫힌 집합을 물어보는 유일한 창구."""
    return {
        "contract_version": CONTRACT_VERSION,
        "types": [
            {"name": p.name, "prefix": p.prefix, "directory": p.directory,
             "ko": p.ko, "en": p.en, "note": p.note}
            for p in PAGE_TYPES.values()
        ],
        "acl_levels": list(ACL_LEVELS),
        "acl_internal_only": sorted(ACL_INTERNAL_ONLY),
        "statuses": list(STATUSES),
        "domains": list(DOMAINS),
        "measurement_bases": list(MEASUREMENT_BASES),
        "confidences": list(CONFIDENCES),
        "required_fields": list(REQUIRED_FIELDS),
        "directories": list(DIRECTORIES),
    }
