"""판정 엔진 (L3) — 승인 그래프 위의 결정론적 룰. **이 파일에 LLM 이 없다.**

모델에게 "이 항목이 준수되었나" 를 묻지 않는다. 물어봐야 할 질문은 셋뿐이고
셋 다 그래프 조회로 답할 수 있다.

    증적이 있는가 · 서명되었는가 · 유효기간 내인가

지표 항목이면 하나 더: 측정값이 임계치를 충족하는가. 그게 전부다.
모델이 한 일은 앞 단계에서 "별첨05 3-2절이 이 통제의 증적이다" 라는 엣지를
제안한 것이고, 그 제안은 사람이 승인했다.

정밀도 우선
----------
결론이 애매하면 판정하지 않고 **판단 유보**로 심사 큐에 넣는다. 커버리지를
늘리려다 심사자가 물량에 압도되면 형식 승인이 발생하고, 그러면 통제 실효성
자체가 무너진다. 커버리지 40~60% · 정밀도 97% 로 시작하는 편이 감사 대응상
낫다는 판단이 룰에 박혀 있다.

재현성
------
모든 판정은 온톨로지·룰셋·기준·조문 4개 버전을 함께 기록한다. 기준이 개정돼도
1년 뒤에 당시 판정을 그대로 재현할 수 있다 (`Store.approved(as_of=...)`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ontology import (
    COMPLIANCE_ONTOLOGY_VERSION,
    DEFERRED,
    EXPIRY_WINDOW_DAYS,
    NOT_APPLICABLE,
    PARTIAL,
    SATISFIED,
    UNSATISFIED,
    CONFIRMED,
    PROVISIONAL,
    VERDICT_LABELS,
    node_id,
)
from .spans import check_citation_force, parse_spans
from .store import (
    Graph,
    Store,
    days_between,
    edge_record,
    node_record,
    now_iso,
    parse_date,
    today_iso,
)



@dataclass
class Assessment:
    """판정 1건. 사람의 확정 서명 전에는 잠정이다."""

    service_uuid: str
    control_code: str
    verdict: str
    raw_verdict: str
    reason: str
    triggers: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    need: int = 0
    have: int = 0
    versions: dict[str, Any] = field(default_factory=dict)
    assessed_at: str = ""
    as_of: str = ""
    #: 결재 상태(잠정/확정). 노드 생애 상태(active/obsolete)와는 다른 축이라
    #: 이름을 갈라 둔다 — 한 칸에 두 의미를 담으면 반드시 충돌한다.
    decision_status: str = PROVISIONAL
    confirmed_by: str = ""
    confirmed_at: str = ""

    @property
    def uuid(self) -> str:
        """같은 기준일에 같은 서비스·통제를 다시 돌리면 같은 판정 노드가 된다."""
        return f"{self.service_uuid}-{self.control_code}-{self.as_of or self.assessed_at[:10]}"

    @property
    def label(self) -> str:
        return VERDICT_LABELS[self.verdict]

    @property
    def deferred(self) -> bool:
        return self.verdict == DEFERRED

    def to_props(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "service_uuid": self.service_uuid,
            "control_code": self.control_code,
            "verdict": self.verdict,
            "raw_verdict": self.raw_verdict,
            "reason": self.reason,
            "triggers": list(self.triggers),
            "evidence_ids": list(self.evidence_ids),
            "need": self.need,
            "have": self.have,
            "versions": self.versions,
            "assessed_at": self.assessed_at,
            "as_of": self.as_of,
            "decision_status": self.decision_status,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.to_props(), "label": self.label}


# --------------------------------------------------------------------------- #
# 판정
# --------------------------------------------------------------------------- #
def adjudicate(
    graph: Graph,
    service_uuid: str,
    control_code: str,
    *,
    ruleset_version: str = "",
    standard_version: str = "",
    metrics: dict[str, dict[str, float]] | None = None,
    conflicts: dict[str, list[str]] | None = None,
    today: str | None = None,
    prior: dict[str, str] | None = None,
) -> Assessment:
    """서비스 × 통제 한 칸을 판정한다.

    prior 는 직전 차수 판정 {control_code: verdict} — 결과가 뒤집히면 유보한다.
    conflicts 는 {문서ID: [불일치 요약]} — 지표 측정값과 같은 성격의 외부 입력이다.
    문서 대조는 그래프 밖의 원문을 읽어야 하므로 판정 안에서 하지 않는다.
    """
    metrics = metrics or {}
    conflicts = conflicts or {}
    today_str = today or today_iso()
    today_date = parse_date(today_str)
    ctrl_id = node_id("Control", code=control_code)
    svc_id = node_id("Service", uuid=service_uuid)
    control = graph.node(ctrl_id)

    versions = _versions(graph, ctrl_id, ruleset_version, standard_version)

    if control is None or control["status"] != "active":
        return Assessment(
            service_uuid, control_code, NOT_APPLICABLE, NOT_APPLICABLE,
            reason=f"Control {control_code} is absent from the approved graph or retired",
            versions=versions, assessed_at=now_iso(), as_of=today_str,
        )

    applies = [e for e in graph.out_edges(ctrl_id, "APPLIES_TO") if e["target"] == svc_id]
    if not applies:
        return Assessment(
            service_uuid, control_code, NOT_APPLICABLE, NOT_APPLICABLE,
            reason="Control does not apply to this service",
            versions=versions, assessed_at=now_iso(), as_of=today_str,
        )

    # --- 증적: 있는가 · 서명되었는가 · 유효기간 내인가 --- #
    required = [
        e for e in graph.out_edges(ctrl_id, "PRODUCES")
        if graph.props(e["target"]).get("required_yn") is True
        and graph.node(e["target"])["status"] == "active"
    ]
    required_ids = {e["target"] for e in required}
    need = len(required_ids)

    satisfied_for: dict[str, str] = {}   # 요구 증적 → 실제 증적
    accepted: list[str] = []             # 인정된 제출물 전부 (요구 명세와 무관하게)
    rejected: list[str] = []
    expiring: list[str] = []
    for edge in graph.out_edges(ctrl_id, "SATISFIED_BY"):
        if edge["props"].get("service_uuid") != service_uuid:
            continue
        evd_id = edge["target"]
        evd = graph.node(evd_id)
        if evd is None or evd["status"] != "active":
            continue
        props = evd["props"]
        if props.get("sign_yn") is not True:
            rejected.append(f"{props.get('title', evd_id)}: unsigned")
            continue
        valid_from, valid_to = parse_date(props.get("valid_from")), parse_date(props.get("valid_to"))
        if today_date and valid_from and today_date < valid_from:
            rejected.append(f"{props.get('title', evd_id)}: not yet valid")
            continue
        if today_date and valid_to and today_date > valid_to:
            rejected.append(f"{props.get('title', evd_id)}: expired")
            continue
        if today_date and valid_to and 0 <= days_between(today_date, valid_to) <= EXPIRY_WINDOW_DAYS:
            expiring.append(props.get("title", evd_id))
        target_required = edge["props"].get("for_required") or evd_id
        satisfied_for[target_required] = evd_id
        accepted.append(evd_id)

    have = len([r for r in required_ids if r in satisfied_for])
    # 판정이 실제로 근거로 삼은 것은 인정된 제출물 전부다. 요구 명세에 매칭된 것만
    # 남기면 구성 검토가 볼 문서가 사라지고, PROV 계보도 실제보다 좁아진다.
    evidence_ids = sorted(set(accepted))

    # --- 지표: 임계치를 충족하는가 --- #
    metric_total = 0
    metric_passed = 0
    metric_notes: list[str] = []
    threshold_undefined: list[str] = []
    metric_missing: list[str] = []
    missing_sections: list[str] = []
    unfilled: list[str] = []
    qualitative = control["props"].get("auto_level") == "L3"

    readings = metrics.get(service_uuid, {})
    for tp_id in graph.targets(ctrl_id, "VERIFIED_BY"):
        tp = graph.node(tp_id)
        if tp is None or tp["status"] != "active":
            continue
        props = tp["props"]
        kind = props.get("kind")
        if kind == "qualitative":
            qualitative = True
            continue
        if kind == "section":
            # 구성 검토 — 서식이 요구한 절이 제출물에 있는가. 내용은 보지 않는다.
            metric_total += 1
            gap, left = _section_gap(graph, props, evidence_ids)
            missing_sections.extend(gap)
            unfilled.extend(left)
            if not gap:
                metric_passed += 1
                metric_notes.append(
                    f"section check passed ({len(props.get('sections') or [])} sections)"
                )
            else:
                metric_notes.append(f"{len(gap)} sections missing: " + ", ".join(gap[:3]))
            continue
        if kind != "metric":
            continue
        metric_total += 1
        metric, operator = props.get("metric"), props.get("operator")
        threshold = props.get("threshold")
        if threshold in (None, "") or operator in (None, ""):
            threshold_undefined.append(str(metric or tp_id))
            continue
        if metric not in readings:
            metric_missing.append(str(metric))
            continue
        value = readings[metric]
        if compare(value, str(operator), float(threshold)):
            metric_passed += 1
            metric_notes.append(
                f"{metric} {value}{props.get('unit', '')} {operator} {threshold} met"
            )
        else:
            metric_notes.append(
                f"{metric} {value}{props.get('unit', '')} {operator} {threshold} not met"
            )

    # 이 판정이 쓴 문서들 사이에 불일치가 보고돼 있는가
    conflict_notes: list[str] = []
    for evd_id in evidence_ids:
        for note in conflicts.get(str(graph.props(evd_id).get("doc_ref", "")), []):
            if note not in conflict_notes:
                conflict_notes.append(note)

    # --- 원 판정 --- #
    total_need = need + metric_total
    total_have = have + metric_passed
    if total_need == 0 and qualitative:
        # 정성 항목만 있는 통제 — 룰이 계산할 것이 없다. 해당없음이 아니라 사람 몫이다.
        raw = DEFERRED
    elif total_need == 0:
        raw = NOT_APPLICABLE
    elif total_have >= total_need:
        raw = SATISFIED
    elif total_have > 0:
        raw = PARTIAL
    else:
        raw = UNSATISFIED

    # --- 판단 유보 트리거 --- #
    triggers: list[str] = []
    if raw != NOT_APPLICABLE:
        if qualitative:
            triggers.append("QUALITATIVE")
        if 0 < have < need:
            triggers.append("PARTIAL_EVIDENCE")
        if threshold_undefined:
            triggers.append("THRESHOLD_UNDEFINED")
        if metric_missing:
            triggers.append("METRIC_MISSING")
        if unfilled:
            # 자리표시자가 남은 것은 미기입으로 보이지만, 참조 시트의 예시문일 수도
            # 있다. 정밀도 우선이라 여기서 미충족으로 단정하지 않고 사람에게 넘긴다.
            triggers.append("TEMPLATE_UNFILLED")
        if conflict_notes:
            # 두 문서가 다른 말을 한다. 어느 쪽이 맞는지는 룰이 정할 일이 아니다.
            triggers.append("DOC_CONFLICT")
        if expiring:
            triggers.append("EVIDENCE_EXPIRING")
        if _amending_provisions(graph, ctrl_id):
            triggers.append("PROVISION_AMENDING")
        if _weak_citations(graph, ctrl_id):
            triggers.append("CITATION_WEAK")
        prior_verdict = (prior or {}).get(control_code)
        if prior_verdict and prior_verdict not in (raw, DEFERRED) and prior_verdict != NOT_APPLICABLE:
            triggers.append("VERDICT_FLIPPED")

    verdict = DEFERRED if triggers else raw

    reason = _reason(
        raw=raw, need=need, have=have, metric_total=metric_total,
        metric_passed=metric_passed, metric_notes=metric_notes,
        qualitative=qualitative, rejected=rejected, expiring=expiring,
        missing_sections=missing_sections, unfilled=unfilled,
        conflict_notes=conflict_notes,
        threshold_undefined=threshold_undefined, metric_missing=metric_missing,
        triggers=triggers,
    )

    return Assessment(
        service_uuid=service_uuid,
        control_code=control_code,
        verdict=verdict,
        raw_verdict=raw,
        reason=reason,
        triggers=triggers,
        evidence_ids=evidence_ids,
        need=total_need,
        have=total_have,
        versions=versions,
        assessed_at=now_iso(),
        as_of=today_str,
    )


def adjudicate_all(
    graph: Graph,
    *,
    service_uuid: str | None = None,
    ruleset_version: str = "",
    standard_version: str = "",
    metrics: dict[str, dict[str, float]] | None = None,
    conflicts: dict[str, list[str]] | None = None,
    today: str | None = None,
    prior: dict[str, dict[str, str]] | None = None,
) -> list[Assessment]:
    """적용된 모든 (서비스 × 통제) 를 판정한다. 판정 대상은 APPLIES_TO 가 정의한다."""
    out: list[Assessment] = []
    pairs: list[tuple[str, str]] = []
    for edge in graph.active_edges():
        if edge["type"] != "APPLIES_TO":
            continue
        svc = graph.props(edge["target"]).get("uuid")
        code = graph.props(edge["source"]).get("code")
        if not svc or not code:
            continue
        if service_uuid and svc != service_uuid:
            continue
        pairs.append((str(svc), str(code)))
    for svc, code in sorted(set(pairs)):
        out.append(adjudicate(
            graph, svc, code,
            ruleset_version=ruleset_version, standard_version=standard_version,
            metrics=metrics, conflicts=conflicts, today=today,
            prior=(prior or {}).get(svc),
        ))
    return out


def compare(value: float, operator: str, threshold: float) -> bool:
    if operator == ">=":
        return value >= threshold
    if operator == ">":
        return value > threshold
    if operator == "<=":
        return value <= threshold
    if operator == "<":
        return value < threshold
    if operator == "==":
        return value == threshold
    if operator == "!=":
        return value != threshold
    raise ValueError(f"알 수 없는 연산자: {operator}")


# --------------------------------------------------------------------------- #
# 판정을 그래프에 남긴다 (PROV 계보)
# --------------------------------------------------------------------------- #
def records_for(
    assessment: Assessment, *, ruleset_version: str = "", agent_id: str = "rule-engine"
) -> list[dict[str, Any]]:
    """판정 → 저널 레코드. 무엇을 근거로 누가 냈는지가 함께 남는다."""
    asmt_id = node_id("Assessment", uuid=assessment.uuid)
    svc_id = node_id("Service", uuid=assessment.service_uuid)
    records = [
        node_record("Assessment", assessment.to_props(), derivation="rule"),
        edge_record("ASSESSED_AS", svc_id, asmt_id, derivation="rule"),
        edge_record("wasAttributedTo", asmt_id,
                    node_id("Agent", agent_id=agent_id), derivation="rule"),
    ]
    if ruleset_version:
        records.append(edge_record(
            "used", asmt_id, node_id("RuleSet", version=ruleset_version), derivation="rule"))
    for evd in assessment.evidence_ids:
        records.append(edge_record("used", asmt_id, evd, derivation="rule"))
    return records


def commit(
    store: Store, assessments: list[Assessment], *,
    ruleset_version: str = "", agent_id: str = "rule-engine",
) -> int:
    records: list[dict[str, Any]] = []
    for a in assessments:
        records.extend(records_for(a, ruleset_version=ruleset_version, agent_id=agent_id))
    return store.append(records)


def confirm(
    store: Store, assessment_uuid: str, *, agent_id: str,
    verdict: str | None = None, note: str = "",
) -> dict[str, Any]:
    """사람의 확정 서명 (게이트 3).

    자동 판정 결과도 이 서명 전에는 잠정이다. 사람이 값을 뒤집으면 그 판정의
    근거는 룰이 아니라 사람이므로 derivation 이 human 으로 바뀐다.
    """
    graph = store.approved()
    asmt_id = node_id("Assessment", uuid=assessment_uuid)
    node = graph.node(asmt_id)
    if node is None:
        raise KeyError(f"판정을 찾을 수 없다: {assessment_uuid}")
    props = dict(node["props"])
    overridden = bool(verdict) and verdict != props.get("verdict")
    if verdict:
        props["verdict"] = verdict
    props["decision_status"] = CONFIRMED
    props["confirmed_by"] = agent_id
    props["confirmed_at"] = now_iso()
    if note:
        props["note"] = note
    store.append([
        node_record("Assessment", props, derivation="human" if overridden else "rule"),
        edge_record("wasAttributedTo", asmt_id,
                    node_id("Agent", agent_id=agent_id), derivation="human"),
    ])
    return props


# --------------------------------------------------------------------------- #
def _versions(
    graph: Graph, ctrl_id: str, ruleset_version: str, standard_version: str
) -> dict[str, Any]:
    """판정 재현에 필요한 4개 버전."""
    provisions = []
    for prv_id in _upstream_provisions(graph, ctrl_id):
        props = graph.props(prv_id)
        provisions.append({
            "uuid": props.get("uuid"),
            "number": props.get("number"),
            "effective_from": props.get("effective_from", ""),
        })
    if not ruleset_version:
        active = graph.of_type("RuleSet")
        ruleset_version = str(active[0]["props"].get("version")) if active else ""
    if not standard_version:
        active = graph.of_type("RuleSet")
        standard_version = str(active[0]["props"].get("standard_version", "")) if active else ""
    return {
        "ontology": COMPLIANCE_ONTOLOGY_VERSION,
        "ruleset": ruleset_version,
        "standard": standard_version,
        "provisions": sorted(provisions, key=lambda p: str(p.get("uuid"))),
    }


def _section_gap(
    graph: Graph, procedure: dict[str, Any], evidence_ids: list[str]
) -> tuple[list[str], list[str]]:
    """요구된 절 중 제출물에 없는 것과, 남아 있는 자리표시자.

    제출물의 절 목록은 적재 시점에 파서가 계산해 Evidence 노드에 박아 둔다.
    판정 시점에 문서를 다시 읽지 않는다 — 판정은 그래프 조회여야 재현되기 때문이다.
    """
    required = [str(x) for x in (procedure.get("sections") or [])]
    if not required:
        return [], []
    have: set[str] = set()
    unfilled: list[str] = []
    for evd_id in evidence_ids:
        props = graph.props(evd_id)
        have.update(_norm(str(x)) for x in (props.get("sections") or []))
        for item in props.get("placeholders") or []:
            why = item.get("why") if isinstance(item, dict) else str(item)
            if why and why not in unfilled:
                unfilled.append(str(why))
    missing = [label for label in required if not _covers(_norm(label), have)]
    return missing, unfilled


def _covers(want: str, have: set[str]) -> bool:
    if not want or want in have:
        return want in have
    return any(want in got or got in want for got in have if got)


def _norm(text: str) -> str:
    return "".join(text.split()).lower()


def _upstream_obligations(graph: Graph, ctrl_id: str) -> list[str]:
    return graph.sources(ctrl_id, "IMPLEMENTED_BY")


def _upstream_provisions(graph: Graph, ctrl_id: str) -> list[str]:
    out: set[str] = set()
    for obl in _upstream_obligations(graph, ctrl_id):
        out.update(graph.sources(obl, "DERIVES"))
    return sorted(out)


def _amending_provisions(graph: Graph, ctrl_id: str) -> list[str]:
    return [
        p for p in _upstream_provisions(graph, ctrl_id)
        if graph.props(p).get("status") == "amending"
    ]


def _weak_citations(graph: Graph, ctrl_id: str) -> list[str]:
    """상위 의무의 주장 강도가 근거를 넘어서면 판정하지 않는다."""
    weak: list[str] = []
    for obl_id in _upstream_obligations(graph, ctrl_id):
        node = graph.node(obl_id)
        if node is None:
            continue
        check = check_citation_force(
            node["props"], parse_spans(node.get("spans")), label=obl_id)
        if not check.ok:
            weak.append(obl_id)
    return weak


def _reason(
    *, raw: str, need: int, have: int, metric_total: int, metric_passed: int,
    metric_notes: list[str], qualitative: bool, rejected: list[str],
    expiring: list[str], threshold_undefined: list[str], metric_missing: list[str],
    missing_sections: list[str], unfilled: list[str], conflict_notes: list[str],
    triggers: list[str],
) -> str:
    parts: list[str] = []
    if need:
        parts.append(f"required evidence {have}/{need}")
    if metric_total:
        parts.append(f"metric/section checks {metric_passed}/{metric_total}")
    if missing_sections:
        parts.append("missing sections: " + ", ".join(missing_sections[:4]))
    if unfilled:
        parts.append("possibly unfilled: " + ", ".join(unfilled[:3]))
    if conflict_notes:
        parts.append("documents disagree: " + "; ".join(conflict_notes[:2]))
    if qualitative:
        parts.append("qualitative control — rules do not decide it")
    if not parts:
        parts.append("no evidence or metric required")
    if rejected:
        parts.append("rejected: " + "; ".join(rejected))
    if expiring:
        parts.append("expiring soon: " + ", ".join(expiring))
    if threshold_undefined:
        parts.append("threshold undefined: " + ", ".join(threshold_undefined))
    if metric_missing:
        parts.append("measurement missing: " + ", ".join(metric_missing))
    if metric_notes:
        parts.append(" / ".join(metric_notes))
    head = f"Rule verdict: {VERDICT_LABELS[raw]}"
    # 룰이 이미 DEFERRED 를 냈으면 화살표를 붙이지 않는다 —
    # "Deferred to reviewer → deferred to reviewer" 가 되어 읽는 사람을 헷갈리게 한다.
    if triggers and raw != DEFERRED:
        head += " → deferred to reviewer"
    return head + " — " + " · ".join(parts)
