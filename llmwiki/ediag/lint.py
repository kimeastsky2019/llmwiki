"""Lint — 위키 무결성 검사 (P4).

Lint 는 주기 작업이다. 생성 직후 1회, 그리고 주 1회. 미루면 기술 부채가 뒤에서
터진다 — 깨진 위키 위에 인덱스를 만들면, 문제를 발견했을 때 소스부터 인덱스까지
전부 다시 만들어야 한다.

**판정은 코드가 한다.** LLM 에게 "이 위키 이상한 데 없어?" 라고 묻지 않는다. 물으면
매번 다른 답이 오고, 통과 여부를 기준으로 배포를 막을 수 없다.

| 검사 | 코드 | 심각도 | 뜻 |
|---|---|---|---|
| 필수 필드 누락 | `schema.*` | error | 컨트랙트 위반 |
| stable_id 중복 | `id.duplicate` | blocker | 어느 쪽이 진짜인지 알 수 없다 |
| ACL 상속 위반 | `acl.inheritance` | **blocker** | 낮은 등급이 높은 등급을 참조 → 배포 차단 |
| 끊어진 링크 | `link.broken` | error | 대상이 없다 |
| 고아 페이지 | `link.orphan` | warning | 아무도 참조하지 않아 도달 불가 |
| 수치 검산 실패 | `numeric.unverified` | warning | 인용 대상에서 제외된다 |
| 단위 라벨 오기 | `unit.label_mismatch` | warning | 계수의 분모가 틀리게 적혀 있다 |
| 계수 만료 임박 | `regulation.expiring` | warning | 개정 반영이 필요하다 |
| 문서 간 모순 | `contradiction.equipment` | warning | 같은 설비의 제원이 다르다 |
| 검토 대기 | `review.pending` | info | 초안 상태 |

blocker 가 하나라도 있으면 `deployable=False` 다. 이 값이 배포 게이트다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import contract
from .page import WikiPage
from .store import WikiStore
from .units import UnitTable, load

SEVERITIES: tuple[str, ...] = ("blocker", "error", "warning", "info")

#: 배포를 막는 심각도. 여기 있는 것이 하나라도 있으면 인덱스를 만들지 않는다.
BLOCKING: frozenset[str] = frozenset({"blocker"})


@dataclass
class Finding:
    code: str
    severity: str
    page: str
    message: str
    hint: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class LintResult:
    findings: list[Finding] = field(default_factory=list)
    pages: int = 0

    def by_severity(self, severity: str) -> list[Finding]:
        return [f for f in self.findings if f.severity == severity]

    @property
    def deployable(self) -> bool:
        return not any(f.severity in BLOCKING for f in self.findings)

    @property
    def clean(self) -> bool:
        """위반 0. 기획서의 Phase 1 게이트가 요구하는 상태."""
        return not [f for f in self.findings if f.severity in ("blocker", "error")]

    def to_dict(self) -> dict[str, Any]:
        counts = {s: len(self.by_severity(s)) for s in SEVERITIES}
        return {
            "pages": self.pages,
            "deployable": self.deployable,
            "clean": self.clean,
            "counts": counts,
            "total": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
        }


# --------------------------------------------------------------------------- #
def run(store: WikiStore, *, table: UnitTable | None = None,
        pages: list[WikiPage] | None = None) -> LintResult:
    t = table or load()
    pages = pages if pages is not None else store.pages()
    findings: list[Finding] = []

    findings += _broken_files(pages)
    findings += _schema(pages)
    findings += _duplicate_ids(pages)
    findings += _links(pages)
    findings += _acl(pages)
    findings += _numeric(pages)
    findings += _units(pages, t)
    findings += _expiry(pages, t)
    findings += _contradictions(pages)
    findings += _pending(pages)

    order = {s: i for i, s in enumerate(SEVERITIES)}
    findings.sort(key=lambda f: (order.get(f.severity, 9), f.code, f.page))
    return LintResult(findings=findings, pages=len(pages))


def _broken_files(pages: list[WikiPage]) -> list[Finding]:
    return [
        Finding("file.unreadable", "error", p.path, p.errors[0],
                hint="front-matter 가 없거나 YAML 이 깨졌다. 파일을 열어 고친다.")
        for p in pages if p.errors
    ]


def _schema(pages: list[WikiPage]) -> list[Finding]:
    out: list[Finding] = []
    for p in pages:
        if p.errors:
            continue
        for issue in p.validate().issues:
            out.append(Finding(
                issue.code, "error" if issue.severity == "error" else "warning",
                p.stable_id or p.path, f"{issue.field}: {issue.message}",
                hint="컨트랙트를 만족하지 못한 페이지는 파이프라인에 진입할 수 없다 (P3)."))
    return out


def _duplicate_ids(pages: list[WikiPage]) -> list[Finding]:
    seen: dict[str, list[str]] = {}
    for p in pages:
        if p.stable_id:
            seen.setdefault(p.stable_id, []).append(p.path)
    return [
        Finding("id.duplicate", "blocker", sid,
                f"stable_id 가 {len(paths)}곳에 있다: {', '.join(paths)}",
                hint="어느 쪽이 진짜인지 코드가 정할 수 없다. 즉시 실패시킨다.")
        for sid, paths in seen.items() if len(paths) > 1
    ]


def _links(pages: list[WikiPage]) -> list[Finding]:
    ids = {p.stable_id for p in pages if p.stable_id}
    referenced: set[str] = set()
    out: list[Finding] = []
    for p in pages:
        for target in p.related:
            if target in ids:
                referenced.add(target)
                continue
            out.append(Finding(
                "link.broken", "error", p.stable_id,
                f"끊어진 링크: [[{target}]]",
                hint="대상 페이지를 만들거나 링크를 지운다.",
                detail={"target": target}))
    for p in pages:
        # 카탈로그(index.md)는 페이지가 아니라 재생성물이라 참조로 세지 않는다.
        if p.stable_id and p.stable_id not in referenced and p.type != "source":
            out.append(Finding(
                "link.orphan", "warning", p.stable_id,
                "아무도 참조하지 않는다 (고아 페이지)",
                hint="인덱스나 상위 페이지에서 연결하거나, 폐기 판정을 내린다."))
    return out


def _acl(pages: list[WikiPage]) -> list[Finding]:
    """P5 의 집행 지점. 여기 걸리면 배포가 막힌다."""
    level = {p.stable_id: p.acl for p in pages if p.stable_id}
    out: list[Finding] = []
    for p in pages:
        for target in p.related:
            target_acl = level.get(target)
            if target_acl is None:
                continue
            if not contract.acl_allows_reference(p.acl, target_acl):
                out.append(Finding(
                    "acl.inheritance", "blocker", p.stable_id,
                    f"{p.acl} 페이지가 {target_acl} 페이지를 참조한다: [[{target}]]",
                    hint="링크 자체가 정보를 흘린다. 참조 방향을 뒤집거나(역링크) "
                         "등급을 맞춘다.",
                    detail={"target": target, "target_acl": target_acl}))
    return out


def _numeric(pages: list[WikiPage]) -> list[Finding]:
    return [
        Finding("numeric.unverified", "warning", p.stable_id,
                "수치 검산을 통과하지 못했다 — 이 페이지의 값은 서비스 응답에서 인용되지 않는다",
                hint="원문이 틀렸는지 입력이 틀렸는지 사람이 판정한다 (P2).")
        for p in pages if p.stable_id and not p.numeric_verified
    ]


def _units(pages: list[WikiPage], t: UnitTable) -> list[Finding]:
    """계수 값 옆에 잘못된 단위가 붙은 곳을 찾는다.

    값은 맞는데 라벨이 틀린 경우가 가장 위험하다 — 다음 사람이 라벨대로 곱해서
    틀린 값을 만든다. `units.yaml` 의 `mislabeled_as` 가 이 검사의 원본이다.
    """
    out: list[Finding] = []
    for f in t.factors:
        if not f.mislabeled_as:
            continue
        value = f"{f.value:g}"
        pattern = re.compile(
            re.escape(value) + r"\s*[\(\[]?\s*" + re.escape(f.mislabeled_as))
        for p in pages:
            if pattern.search(p.body):
                out.append(Finding(
                    "unit.label_mismatch", "warning", p.stable_id,
                    f"{f.label}({value}) 옆에 `{f.mislabeled_as}` 가 붙어 있다. "
                    f"올바른 단위는 `{f.unit}` 다",
                    hint="값은 맞고 라벨이 틀린 경우다. 그대로 두면 다음 사람이 "
                         "라벨대로 곱해 값을 틀리게 만든다.",
                    detail={"code": f.code, "correct_unit": f.unit}))
    return out


def _expiry(pages: list[WikiPage], t: UnitTable) -> list[Finding]:
    out: list[Finding] = []
    expiring = t.expiring()
    if not expiring:
        return out
    targets = [p for p in pages if p.type == "regulation"] or pages[:1]
    for f in expiring:
        days = f.expires_in()
        for p in targets:
            if f.label not in p.body and f.code not in p.body:
                continue
            out.append(Finding(
                "regulation.expiring", "warning", p.stable_id,
                f"{f.label} 의 유효기간이 {days}일 남았다 (만료 {f.valid_until})"
                if days is not None and days >= 0 else
                f"{f.label} 의 유효기간이 지났다 (만료 {f.valid_until})",
                hint="`data/units.yaml` 을 개정하고 규정 페이지를 다시 생성한다.",
                detail={"code": f.code, "valid_until": f.valid_until, "days": days}))
    return out


def _contradictions(pages: list[WikiPage]) -> list[Finding]:
    """같은 설비의 제원이 문서마다 다른 경우.

    기획서는 이 항목을 'Grok 판정 → 사람 검토 큐' 로 뒀다. 다만 **탐지**는 룰이 할 수
    있다 — 같은 용량·같은 종류인데 모델·제작사·제작년도가 다르면 둘 중 하나가 틀렸다.
    무엇이 맞는지는 사람이 정한다.
    """
    groups: dict[tuple, list[WikiPage]] = {}
    for p in pages:
        spec = p.front_matter.get("equipment")
        if p.type != "equipment" or not isinstance(spec, dict):
            continue
        groups.setdefault((spec.get("term"), spec.get("capacity"),
                           spec.get("capacity_unit")), []).append(p)
    out: list[Finding] = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        for attr in ("model", "maker", "year"):
            values = {
                str((p.front_matter.get("equipment") or {}).get(attr, "")).strip()
                for p in group
            }
            values.discard("")
            if len(values) > 1:
                out.append(Finding(
                    "contradiction.equipment", "warning", group[0].stable_id,
                    f"같은 설비({key[0]} {key[1]}{key[2]})의 {attr} 가 다르다: "
                    f"{', '.join(sorted(values))}",
                    hint="문서 간 모순이다. 어느 쪽이 맞는지는 사람이 판정한다.",
                    detail={"pages": [p.stable_id for p in group], "attribute": attr}))
    return out


def _pending(pages: list[WikiPage]) -> list[Finding]:
    out: list[Finding] = []
    for p in pages:
        if not p.stable_id:
            continue
        if p.status == "draft":
            out.append(Finding("review.pending", "info", p.stable_id,
                               "초안 상태다 — 검색은 되지만 검토 완료로 표시되지 않는다",
                               hint="관리자 화면의 검증 큐에서 확인한다."))
        if "[검토 필요]" in p.body:
            out.append(Finding("review.marker", "info", p.stable_id,
                               f"본문에 [검토 필요] 표시가 "
                               f"{p.body.count('[검토 필요]')}개 있다",
                               hint="규칙이 답할 수 없어 비워 둔 자리다."))
    return out
