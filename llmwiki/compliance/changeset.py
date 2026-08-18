"""커밋 결재 (L6) — 지식·기준 변경을 코드 리뷰처럼 다룬다.

LLM 자동화를 안전하게 만드는 마지막 장치다. sLM 의 제안이든 외부 세그먼트에서
반입된 규제 개정이든, 전부 **같은 게이트**를 지난다. 통제 지점이 하나로 모인다.

게이트는 둘이다.
    게이트 1 — 기계 검증: 형상(SHACL 격) · 근거 스팬 실재 · 인용 강도 · 제안 권한
    게이트 2 — 사람 결재: diff 와 영향분석을 보고 병합

승인 등급은 **하위호환 파괴 여부**로 가른다. 배점·임계치를 바꾸는 변경(G3)은
기존 판정을 전량 재검토로 돌리기 때문에, 노드 하나 추가(G2)와 같은 결재선에
둘 수 없다. 물리 삭제는 등급이 없다 — 불허다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from .analysis import affected_controls
from .ontology import edge_key, node_id
from .store import (
    Graph,
    Store,
    edge_record,
    node_record,
    now_iso,
    obsolete_edge_record,
    obsolete_record,
    today_iso,
)
from .verify import OPS, validate_ops

# --- 등급 ------------------------------------------------------------------ #
G1, G2, G3, G4 = "G1", "G2", "G3", "G4"
FORBIDDEN = "FORBIDDEN"

GRADES: dict[str, dict[str, str]] = {
    G1: {
        "approver": "Domain owner",
        "scope": "Property enrichment, added evidence links, label fixes",
        "breaking": "no",
    },
    G2: {
        "approver": "AI governance officer",
        "scope": "New provisions, obligations and controls; new mapping edges",
        "breaking": "no",
    },
    G3: {
        "approver": "AI governance officer + migration plan",
        "scope": "Threshold and scoring changes, automation-level changes, mapping predicate changes, node retirement",
        "breaking": "yes",
    },
    G4: {
        "approver": "AI governance committee",
        "scope": "Standard version bumps, ruleset changes, ontology structure changes",
        "breaking": "yes",
    },
    FORBIDDEN: {
        "approver": "Not permitted",
        "scope": "Hard delete of nodes or edges — only obsolete + replaced_by is allowed",
        "breaking": "-",
    },
}

BREAKING_GRADES = (G3, G4)

#: G3 로 올리는 속성들. 이 값이 바뀌면 기존 판정이 뒤집힐 수 있다.
CRITICAL_PROPS: dict[str, tuple[str, ...]] = {
    "TestProcedure": ("threshold", "operator", "metric", "kind"),
    "Control": ("auto_level",),
    "Obligation": ("level",),
    "Evidence": ("required_yn",),
}

CRITICAL_EDGE_PROPS: tuple[str, ...] = ("mapping_type", "for_required")

# --- 상태 ------------------------------------------------------------------ #
PENDING = "pending_review"
APPROVED = "approved"
REJECTED = "rejected"
BLOCKED = "blocked"  # 게이트 1 실패


# --------------------------------------------------------------------------- #
@dataclass
class ChangeSet:
    changeset_id: str
    proposer: dict[str, str]           # {"type": "SoftwareAgent", "id": "slm-extract-v2.3"}
    ops: list[dict[str, Any]] = field(default_factory=list)
    source: dict[str, str] | None = None
    status: str = PENDING
    grade: str = G1
    impact: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "changeset_id": self.changeset_id,
            "proposer": self.proposer,
            "source": self.source,
            "ops": self.ops,
            "status": self.status,
            "grade": self.grade,
            "impact": self.impact,
            "checks": self.checks,
            "created_at": self.created_at,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "review_note": self.review_note,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ChangeSet":
        return cls(
            changeset_id=raw["changeset_id"],
            proposer=raw.get("proposer", {}),
            ops=raw.get("ops", []),
            source=raw.get("source"),
            status=raw.get("status", PENDING),
            grade=raw.get("grade", G1),
            impact=raw.get("impact", {}),
            checks=raw.get("checks", {}),
            created_at=raw.get("created_at", ""),
            reviewed_by=raw.get("reviewed_by", ""),
            reviewed_at=raw.get("reviewed_at", ""),
            review_note=raw.get("review_note", ""),
        )


def normalize_op(op: dict[str, Any]) -> dict[str, Any]:
    """`"node create"` 처럼 공백으로 쓴 것도 받는다."""
    out = dict(op)
    name = str(out.get("op", "")).strip().replace(" ", ".")
    out["op"] = name
    return out


def new_changeset_id(store: Store, *, day: str | None = None) -> str:
    day = (day or today_iso()).replace("-", "")
    existing = [c for c in store.read_changesets() if c.startswith(f"cs_{day}_")]
    return f"cs_{day}_{len(existing) + 1:03d}"


# --------------------------------------------------------------------------- #
# 등급 판정
# --------------------------------------------------------------------------- #
def grade_of(graph: Graph, ops: Iterable[dict[str, Any]]) -> str:
    """가장 높은 등급이 그 ChangeSet 의 등급이다."""
    worst = G1
    order = {G1: 1, G2: 2, G3: 3, G4: 4, FORBIDDEN: 9}

    def raise_to(grade: str) -> None:
        nonlocal worst
        if order[grade] > order[worst]:
            worst = grade

    for raw in ops:
        op = normalize_op(raw)
        name = op["op"]
        if name not in OPS:
            raise_to(FORBIDDEN)      # delete 를 포함해 정의되지 않은 연산은 전부 불허
            continue

        if name == "node.obsolete" or name == "edge.obsolete":
            raise_to(G3)             # 폐기는 기존 판정을 흔든다
            continue

        if name == "node.create":
            ntype = op.get("node_type", "")
            props = op.get("props", {})
            if ntype in ("RuleSet",):
                raise_to(G4)
                continue
            try:
                nid = node_id(ntype, **props)
            except (KeyError, ValueError):
                raise_to(G2)
                continue
            current = graph.node(nid)
            if current is None:
                raise_to(G2)         # 신규 노드
                continue
            # 기존 노드 — 무엇이 바뀌는지 본다
            critical = CRITICAL_PROPS.get(ntype, ())
            changed_critical = [
                k for k, v in props.items()
                if k in critical and current["props"].get(k) != v
            ]
            raise_to(G3 if changed_critical else G1)
            continue

        if name == "edge.create":
            etype = op.get("edge_type", "")
            props = op.get("props", {})
            try:
                key = edge_key(etype, op.get("source", ""), op.get("target", ""), props)
            except KeyError:
                raise_to(G2)
                continue
            current = graph.edges.get(key)
            if current is None:
                raise_to(G2)
                continue
            changed_critical = [
                k for k, v in props.items()
                if k in CRITICAL_EDGE_PROPS and current["props"].get(k) != v
            ]
            raise_to(G3 if changed_critical else G1)

    return worst


# --------------------------------------------------------------------------- #
# 영향분석 — 병합 전에 계산한다
# --------------------------------------------------------------------------- #
def impact_of(graph: Graph, ops: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """이 변경이 어떤 통제·판정·서비스에 닿는지. 결재자가 보는 숫자다."""
    touched: set[str] = set()
    for raw in ops:
        op = normalize_op(raw)
        name = op["op"]
        if name == "node.create":
            try:
                touched.add(node_id(op.get("node_type", ""), **op.get("props", {})))
            except (KeyError, ValueError):
                continue
        elif name == "node.obsolete":
            touched.add(op.get("id", ""))
        elif name == "edge.create":
            touched.add(op.get("source", ""))
            touched.add(op.get("target", ""))
        elif name == "edge.obsolete":
            parts = op.get("key", "").split("|")
            if len(parts) >= 3:
                touched.update(parts[1:3])
    touched.discard("")

    controls = affected_controls(graph, touched)
    assessments = [
        a for a in graph.of_type("Assessment")
        if a["props"].get("control_code") in {graph.props(c).get("code") for c in controls}
    ]
    services = {a["props"].get("service_uuid") for a in assessments}
    services |= {
        graph.props(e["target"]).get("uuid")
        for c in controls for e in graph.out_edges(c, "APPLIES_TO")
    }
    services.discard(None)

    grade = grade_of(graph, ops)
    return {
        "touched_nodes": sorted(touched),
        "affected_controls": len(controls),
        "affected_control_codes": sorted(
            filter(None, (graph.props(c).get("code") for c in controls))
        ),
        "affected_assessments": len(assessments),
        "affected_services": len(services),
        "breaking": grade in BREAKING_GRADES,
    }


# --------------------------------------------------------------------------- #
# 제안 → 결재
# --------------------------------------------------------------------------- #
def stage(
    store: Store,
    ops: Iterable[dict[str, Any]],
    *,
    proposer: dict[str, str],
    source: dict[str, str] | None = None,
    changeset_id: str | None = None,
) -> ChangeSet:
    """게이트 1 을 돌리고 결재 큐에 올린다.

    기계 검증에서 떨어지면 `blocked` 로 남는다 — 사람 앞에 가지 않는다.
    """
    ops = [normalize_op(o) for o in ops]
    graph = store.approved()
    cs = ChangeSet(
        changeset_id=changeset_id or new_changeset_id(store),
        proposer=proposer,
        source=source,
        ops=ops,
        created_at=now_iso(),
    )
    result = validate_ops(
        graph, ops,
        documents=store.documents(),
        proposer_kind=proposer.get("type", ""),
    )
    cs.checks = {
        "shacl": "PASS" if result.ok else "FAIL",
        "issues": [i.__dict__ for i in result.issues],
    }
    cs.grade = grade_of(graph, ops)
    cs.impact = impact_of(graph, ops)
    if cs.grade == FORBIDDEN:
        cs.checks["shacl"] = "FAIL"
        cs.checks.setdefault("issues", []).append(
            {"level": "error", "code": "op.forbidden",
             "message": "Hard deletes are forbidden — use obsolete + replaced_by"}
        )
    cs.status = PENDING if cs.checks["shacl"] == "PASS" else BLOCKED
    store.put_changeset(cs.to_dict())
    return cs


def preview(store: Store, cs: ChangeSet) -> Graph:
    """제안본 뷰 — 승인본에 ops 를 얹은 가상 그래프. 저널에는 쓰지 않는다."""
    return store.replay(_records(cs), base=store.approved())


def diff(store: Store, cs: ChangeSet) -> dict[str, Any]:
    """결재 화면에 보여줄 diff."""
    before = store.approved()
    after = preview(store, cs)
    added_nodes = [n for nid, n in after.nodes.items() if nid not in before.nodes]
    added_edges = [e for k, e in after.edges.items() if k not in before.edges]
    changed_nodes = []
    for nid, node in after.nodes.items():
        old = before.nodes.get(nid)
        if old is None:
            continue
        deltas = {
            k: [old["props"].get(k), v]
            for k, v in node["props"].items() if old["props"].get(k) != v
        }
        if deltas:
            changed_nodes.append({"id": nid, "type": node["type"], "changes": deltas})
    return {
        "added_nodes": added_nodes,
        "added_edges": added_edges,
        "changed_nodes": changed_nodes,
        "obsoleted": [
            nid for nid, n in after.nodes.items()
            if n["status"] == "obsolete" and before.nodes.get(nid, {}).get("status") != "obsolete"
        ],
    }


def approve(
    store: Store, changeset_id: str, *, approver: str, note: str = ""
) -> ChangeSet:
    """게이트 2 통과 — 저널에 병합한다. 여기서부터 판정 엔진이 본다."""
    raw = store.changeset(changeset_id)
    if raw is None:
        raise KeyError(f"변경 제안을 찾을 수 없다: {changeset_id}")
    cs = ChangeSet.from_dict(raw)
    if cs.status == APPROVED:
        return cs
    if cs.status != PENDING:
        raise ValueError(
            f"{changeset_id}: 상태가 {cs.status} 라 승인할 수 없다 (기계 검증 통과분만 결재)"
        )
    store.append(_records(cs))
    cs.status = APPROVED
    cs.reviewed_by = approver
    cs.reviewed_at = now_iso()
    cs.review_note = note
    store.put_changeset(cs.to_dict())
    return cs


def reject(store: Store, changeset_id: str, *, reviewer: str, note: str = "") -> ChangeSet:
    raw = store.changeset(changeset_id)
    if raw is None:
        raise KeyError(f"변경 제안을 찾을 수 없다: {changeset_id}")
    cs = ChangeSet.from_dict(raw)
    cs.status = REJECTED
    cs.reviewed_by = reviewer
    cs.reviewed_at = now_iso()
    cs.review_note = note
    store.put_changeset(cs.to_dict())
    return cs


def _records(cs: ChangeSet) -> list[dict[str, Any]]:
    """ChangeSet ops → 저널 레코드."""
    out: list[dict[str, Any]] = []
    for raw in cs.ops:
        op = normalize_op(raw)
        name = op["op"]
        if name == "node.create":
            out.append(node_record(
                op["node_type"], op["props"],
                derivation=op.get("derivation"), spans=op.get("spans", []),
                changeset=cs.changeset_id,
            ))
        elif name == "edge.create":
            out.append(edge_record(
                op["edge_type"], op["source"], op["target"], op.get("props"),
                derivation=op.get("derivation"), spans=op.get("spans", []),
                changeset=cs.changeset_id,
            ))
        elif name == "node.obsolete":
            out.append(obsolete_record(
                op["id"], op.get("replaced_by", ""), changeset=cs.changeset_id))
        elif name == "edge.obsolete":
            out.append(obsolete_edge_record(op["key"], changeset=cs.changeset_id))
    return out


# --------------------------------------------------------------------------- #
# ops 만들기 (제안기·시드가 함께 쓴다)
# --------------------------------------------------------------------------- #
def create_node(
    node_type: str, props: dict[str, Any], *,
    spans: list[dict[str, Any]] | None = None, derivation: str | None = None,
) -> dict[str, Any]:
    return {
        "op": "node.create", "node_type": node_type, "props": props,
        "spans": spans or [], "derivation": derivation,
    }


def create_edge(
    edge_type: str, source: str, target: str,
    props: dict[str, Any] | None = None, *,
    spans: list[dict[str, Any]] | None = None, derivation: str | None = None,
) -> dict[str, Any]:
    return {
        "op": "edge.create", "edge_type": edge_type, "source": source,
        "target": target, "props": props or {}, "spans": spans or [],
        "derivation": derivation,
    }


def obsolete_node(node_ident: str, replaced_by: str = "") -> dict[str, Any]:
    return {"op": "node.obsolete", "id": node_ident, "replaced_by": replaced_by}


def summary_line(cs: ChangeSet) -> str:
    kinds: dict[str, int] = {}
    for op in cs.ops:
        name = normalize_op(op)["op"]
        kinds[name] = kinds.get(name, 0) + 1
    body = ", ".join(f"{k} {v}" for k, v in sorted(kinds.items()))
    return f"{cs.changeset_id} [{cs.grade}] {cs.status} — {body}"


def dumps(cs: ChangeSet) -> str:
    return json.dumps(cs.to_dict(), ensure_ascii=False, indent=2)


__all__ = [
    "APPROVED", "BLOCKED", "BREAKING_GRADES", "ChangeSet", "FORBIDDEN",
    "G1", "G2", "G3", "G4", "GRADES", "PENDING", "REJECTED",
    "approve", "create_edge", "create_node", "diff", "dumps", "grade_of",
    "impact_of", "new_changeset_id", "obsolete_node", "preview", "reject",
    "stage", "summary_line",
]
