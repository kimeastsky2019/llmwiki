"""검증 (L4) — 형상 검증 · 근거 스팬 대조 · 인용 강도 · 골드셋 회귀 · 감사 지표.

두 곳에서 쓴다.

* **게이트 1** (`validate_ops`) — 제안이 사람 앞에 가기 전에 기계가 먼저 거른다.
  여기서 걸리는 대표적인 것: 존재하지 않는 오프셋을 가리키는 근거(=환각),
  권고 조문을 근거로 필수 의무를 주장하는 제안, sLM 이 만들려 한 판정 노드.
* **상시 점검** (`validate_graph`) — 승인 그래프가 헌법 셋을 지키는지.

골드셋을 **그래프 구축 전에** 만들어야 하는 이유가 여기 있다. 공개 벤치마크는
이 도메인의 성능을 예측하지 못하므로, 우리 기준으로 재는 자를 먼저 만들어 두지
않으면 나중에는 "좋아 보인다" 밖에 말할 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .ontology import (
    AGENT_KINDS,
    AUTO_LEVELS,
    DEFERRED,
    EDGE_TYPES,
    MAPPING_TYPES,
    NODE_STATUSES,
    NODE_TYPES,
    OBLIGATION_LEVELS,
    OPERATORS,
    PROCEDURE_KINDS,
    VERDICTS,
    node_id,
    type_of,
)
from .rules import Assessment, adjudicate
from .spans import check_citation_force, parse_spans, verify_span
from .store import Graph, Store

#: 허용된 변경 연산. 여기 없는 것은 전부 불허다 — 특히 물리 삭제.
OPS: tuple[str, ...] = ("node.create", "edge.create", "node.obsolete", "edge.obsolete")

#: 속성별 닫힌 집합
_ENUMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("Control", "auto_level"): AUTO_LEVELS,
    ("Obligation", "level"): OBLIGATION_LEVELS,
    ("TestProcedure", "kind"): PROCEDURE_KINDS,
    ("TestProcedure", "operator"): OPERATORS,
    ("Agent", "kind"): AGENT_KINDS,
    ("Assessment", "verdict"): VERDICTS,
}

_EDGE_ENUMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("DERIVES", "mapping_type"): MAPPING_TYPES,
    ("IMPLEMENTED_BY", "mapping_type"): MAPPING_TYPES,
}


@dataclass
class Issue:
    level: str
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"[{self.level}] {self.code}: {self.message}"


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, code: str, message: str) -> None:
        self.issues.append(Issue(level, code, message))


# --------------------------------------------------------------------------- #
# 승인 그래프 검증
# --------------------------------------------------------------------------- #
def validate_graph(graph: Graph, documents: dict[str, str] | None = None) -> ValidationResult:
    """승인 그래프가 스키마와 헌법 셋을 지키는지."""
    r = ValidationResult()

    for nid, node in graph.nodes.items():
        ntype = node["type"]
        spec = NODE_TYPES.get(ntype)
        if spec is None:
            r.add("error", "node.type", f"{nid}: unknown node type {ntype}")
            continue
        if spec.staging:
            r.add("error", "node.staging",
                  f"{nid}: {ntype} is proposal-only but appears in the approved graph")
        props = node["props"]
        for key in spec.required:
            if props.get(key) in (None, ""):
                r.add("error", "node.required", f"{nid}: required property {key} is missing")
        try:
            if node_id(ntype, **props) != nid:
                r.add("error", "node.id", f"{nid}: ID does not follow the id_parts rule")
        except (KeyError, ValueError):
            r.add("error", "node.id", f"{nid}: ID cannot be reconstructed")
        if node["status"] not in NODE_STATUSES:
            r.add("error", "node.status", f"{nid}: unknown status {node['status']}")
        _check_enums(r, nid, ntype, props)

        spans = parse_spans(node.get("spans"))
        if spec.requires_span and not spans:
            r.add("error", "span.required",
                  f"{nid}: {ntype} requires a source span — no unsourced facts")
        for span in spans:
            for issue in verify_span(span, documents).issues:
                r.add("error", issue.code, f"{nid}: {issue.message}")
        for issue in check_citation_force(props, spans, label=nid).issues:
            r.add("error", issue.code, issue.message)

        # 판정은 룰이나 사람이 낸다 — 모델이 낼 수 없다
        if ntype == "Assessment" and node["derivation"] not in ("rule", "human"):
            r.add("error", "assessment.derivation",
                  f"{nid}: assessment derivation is {node['derivation']} — "
                  "only a rule or a human may issue a verdict")
        if node["status"] == "obsolete" and not props.get("replaced_by"):
            r.add("warning", "node.replaced_by", f"{nid}: retired but has no replacement node")

    for key, edge in graph.edges.items():
        etype = edge["type"]
        spec = EDGE_TYPES.get(etype)
        if spec is None:
            r.add("error", "edge.type", f"{key}: unknown edge type {etype}")
            continue
        if spec.staging:
            r.add("error", "edge.staging", f"{key}: {etype} is proposal-only")
        src, dst = edge["source"], edge["target"]
        if src not in graph.nodes:
            r.add("error", "edge.dangling", f"{key}: source node missing — {src}")
        elif graph.nodes[src]["type"] not in spec.domain:
            r.add("error", "edge.domain",
                  f"{key}: source is {graph.nodes[src]['type']} (allowed: {spec.domain})")
        if dst not in graph.nodes:
            r.add("error", "edge.dangling", f"{key}: target node missing — {dst}")
        elif graph.nodes[dst]["type"] not in spec.range:
            r.add("error", "edge.range",
                  f"{key}: target is {graph.nodes[dst]['type']} (allowed: {spec.range})")
        for prop, allowed in ((p, a) for (t, p), a in _EDGE_ENUMS.items() if t == etype):
            value = edge["props"].get(prop)
            if value not in (None, "") and value not in allowed:
                r.add("error", "edge.enum", f"{key}: {prop}={value} is not an allowed value")
        spans = parse_spans(edge.get("spans"))
        if spec.requires_span and not spans and edge["status"] == "active":
            r.add("error", "span.required", f"{key}: {etype} requires a source span")
        for span in spans:
            for issue in verify_span(span, documents).issues:
                r.add("error", issue.code, f"{key}: {issue.message}")

    # PRODUCES 는 요구 증적만 가리킨다
    for edge in graph.active_edges():
        if edge["type"] != "PRODUCES":
            continue
        if graph.props(edge["target"]).get("required_yn") is not True:
            r.add("warning", "produces.required",
                  f"{edge['key']}: PRODUCES target is not required_yn=True")
    return r


def validate_journal(store: Store) -> ValidationResult:
    """저널에 삭제 연산이 없는지 — '삭제 없음' 헌법의 실제 검사."""
    r = ValidationResult()
    for rec in store.read_journal():
        if rec.get("op") not in ("upsert", "obsolete"):
            r.add("error", "journal.op",
                  f"seq {rec.get('seq')}: operation {rec.get('op')} is not allowed — nothing is deleted")
    return r


# --------------------------------------------------------------------------- #
# 게이트 1 — 제안 검증
# --------------------------------------------------------------------------- #
def validate_ops(
    graph: Graph,
    ops: Iterable[dict[str, Any]],
    *,
    documents: dict[str, str] | None = None,
    proposer_kind: str = "",
) -> ValidationResult:
    """변경 제안이 병합될 자격이 있는지. 사람 앞에 가기 전의 기계 검사다."""
    r = ValidationResult()
    ops = [dict(o, op=str(o.get("op", "")).strip().replace(" ", ".")) for o in ops]
    creating: set[str] = set()

    for op in ops:
        if op["op"] == "node.create":
            try:
                creating.add(node_id(op.get("node_type", ""), **op.get("props", {})))
            except (KeyError, ValueError):
                pass

    for i, op in enumerate(ops):
        tag = f"ops[{i}]"
        name = op["op"]
        if name not in OPS:
            r.add("error", "op.unknown",
                  f"{tag}: operation '{name}' is not allowed — hard deletes are forbidden")
            continue

        if name == "node.create":
            ntype = op.get("node_type", "")
            spec = NODE_TYPES.get(ntype)
            if spec is None:
                r.add("error", "op.node_type", f"{tag}: unknown node type {ntype}")
                continue
            if proposer_kind == "SoftwareAgent" and not spec.llm_proposable:
                r.add("error", "authority.propose",
                      f"{tag}: an sLM may not propose {ntype} — propose/decide/confirm stay separate")
            props = op.get("props", {})
            for key in spec.required:
                if props.get(key) in (None, ""):
                    r.add("error", "node.required", f"{tag}: required property {key} is missing")
            try:
                node_id(ntype, **props)
            except (KeyError, ValueError) as exc:
                r.add("error", "node.id", f"{tag}: {exc}")
            _check_enums(r, tag, ntype, props)

            spans = parse_spans(op.get("spans"))
            if spec.requires_span and not spans:
                r.add("error", "span.required",
                      f"{tag}: {ntype} requires a source span — no unsourced facts")
            for span in spans:
                for issue in verify_span(span, documents).issues:
                    r.add("error", issue.code, f"{tag}: {issue.message}")
            for issue in check_citation_force(props, spans, label=tag).issues:
                r.add("error", issue.code, issue.message)

        elif name == "edge.create":
            etype = op.get("edge_type", "")
            spec = EDGE_TYPES.get(etype)
            if spec is None:
                r.add("error", "op.edge_type", f"{tag}: unknown edge type {etype}")
                continue
            if proposer_kind == "SoftwareAgent" and not spec.llm_proposable:
                r.add("error", "authority.propose",
                      f"{tag}: an sLM may not propose a {etype} edge")
            src, dst = op.get("source", ""), op.get("target", "")
            for side, ident, allowed in (
                ("source", src, spec.domain),
                ("target", dst, spec.range),
            ):
                if not ident:
                    r.add("error", "edge.missing", f"{tag}: {side} node is empty")
                    continue
                if ident not in graph.nodes and ident not in creating:
                    r.add("error", "edge.dangling",
                          f"{tag}: {side} node is in neither the approved graph nor this proposal — {ident}")
                    continue
                kind = type_of(ident)
                if kind and kind not in allowed:
                    r.add("error", f"edge.{'domain' if side == 'source' else 'range'}",
                          f"{tag}: {side}가 {kind} (허용 {allowed})")
            props = op.get("props", {})
            for prop, allowed in ((p, a) for (t, p), a in _EDGE_ENUMS.items() if t == etype):
                value = props.get(prop)
                if value not in (None, "") and value not in allowed:
                    r.add("error", "edge.enum", f"{tag}: {prop}={value} is not an allowed value")
            spans = parse_spans(op.get("spans"))
            if spec.requires_span and not spans:
                r.add("error", "span.required", f"{tag}: {etype} requires a source span")
            for span in spans:
                for issue in verify_span(span, documents).issues:
                    r.add("error", issue.code, f"{tag}: {issue.message}")

        elif name == "node.obsolete":
            nid = op.get("id", "")
            if nid not in graph.nodes:
                r.add("error", "obsolete.missing", f"{tag}: nothing to retire — {nid}")
            replaced = op.get("replaced_by", "")
            if replaced and replaced not in graph.nodes and replaced not in creating:
                r.add("error", "obsolete.replaced_by",
                      f"{tag}: replacement node not found — {replaced}")

        elif name == "edge.obsolete":
            if op.get("key", "") not in graph.edges:
                r.add("error", "obsolete.missing", f"{tag}: no such edge to retire")

    return r


def _check_enums(r: ValidationResult, tag: str, ntype: str, props: dict[str, Any]) -> None:
    for (t, prop), allowed in _ENUMS.items():
        if t != ntype:
            continue
        value = props.get(prop)
        if value not in (None, "") and value not in allowed:
            r.add("error", "node.enum", f"{tag}: {prop}={value} is not an allowed value ({allowed})")


# --------------------------------------------------------------------------- #
# 골드셋 회귀 · 감사 지표
# --------------------------------------------------------------------------- #
@dataclass
class GoldsetReport:
    total: int = 0
    decided: int = 0
    correct: int = 0
    deferred: int = 0
    coverage: float = 0.0
    precision: float = 0.0
    kappa: float = 0.0
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    misses: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """판정한 것은 틀리지 않아야 한다 — 유보는 실패가 아니다."""
        return self.decided == self.correct

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total, "decided": self.decided, "correct": self.correct,
            "deferred": self.deferred, "coverage": round(self.coverage, 4),
            "precision": round(self.precision, 4), "kappa": round(self.kappa, 4),
            "confusion": self.confusion, "misses": self.misses,
            "result": "PASS" if self.passed else "FAIL",
        }


def run_goldset(
    graph: Graph,
    goldset: list[dict[str, Any]],
    *,
    metrics: dict[str, dict[str, float]] | None = None,
    ruleset_version: str = "",
    today: str | None = None,
) -> GoldsetReport:
    """골드셋으로 판정 엔진을 잰다.

    커버리지(자동 판정 비율)와 정밀도(판정한 것 중 맞은 비율)를 나눠서 본다.
    유보는 오답이 아니다 — 유보하도록 설계했기 때문이다. 대신 커버리지가 내려간다.
    """
    report = GoldsetReport(total=len(goldset))
    pairs: list[tuple[str, str]] = []
    for case in goldset:
        expected = str(case.get("expected", ""))
        result: Assessment = adjudicate(
            graph, str(case.get("service", "")), str(case.get("control", "")),
            ruleset_version=ruleset_version, metrics=metrics, today=today,
        )
        actual = result.verdict
        report.confusion.setdefault(expected, {})
        report.confusion[expected][actual] = report.confusion[expected].get(actual, 0) + 1
        if actual == DEFERRED:
            report.deferred += 1
            continue
        report.decided += 1
        pairs.append((expected, actual))
        if actual == expected:
            report.correct += 1
        else:
            report.misses.append({
                "service": case.get("service"), "control": case.get("control"),
                "expected": expected, "actual": actual, "reason": result.reason,
            })
    report.coverage = report.decided / report.total if report.total else 0.0
    report.precision = report.correct / report.decided if report.decided else 0.0
    report.kappa = cohen_kappa(pairs)
    return report


def cohen_kappa(pairs: list[tuple[str, str]]) -> float:
    """두 평정자(골드셋 vs 엔진)의 일치도. 우연 일치를 걷어낸 값이다."""
    n = len(pairs)
    if n == 0:
        return 0.0
    labels = sorted({a for a, _ in pairs} | {b for _, b in pairs})
    agree = sum(1 for a, b in pairs if a == b)
    po = agree / n
    pe = 0.0
    for label in labels:
        pa = sum(1 for a, _ in pairs if a == label) / n
        pb = sum(1 for _, b in pairs if b == label) / n
        pe += pa * pb
    if pe >= 1.0:
        return 1.0 if po >= 1.0 else 0.0
    return (po - pe) / (1 - pe)


def audit_metrics(assessments: list[Assessment]) -> dict[str, Any]:
    """감사에 제출할 수치. '얼마나 자동으로 처리했고 얼마를 사람에게 넘겼나'."""
    total = len(assessments)
    by_verdict: dict[str, int] = {}
    by_trigger: dict[str, int] = {}
    for a in assessments:
        by_verdict[a.verdict] = by_verdict.get(a.verdict, 0) + 1
        for t in a.triggers:
            by_trigger[t] = by_trigger.get(t, 0) + 1
    deferred = by_verdict.get(DEFERRED, 0)
    return {
        "total": total,
        "decided": total - deferred,
        "deferred": deferred,
        "auto_rate": round((total - deferred) / total, 4) if total else 0.0,
        "by_verdict": dict(sorted(by_verdict.items())),
        "by_trigger": dict(sorted(by_trigger.items(), key=lambda kv: -kv[1])),
    }


__all__ = [
    "GoldsetReport", "Issue", "OPS", "ValidationResult", "audit_metrics",
    "cohen_kappa", "run_goldset", "validate_graph", "validate_journal", "validate_ops",
]
