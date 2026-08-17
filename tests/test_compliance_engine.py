"""저장소 · 커밋 결재 · 판정 엔진 — 시드 데이터 위에서 전체 흐름을 고정한다.

이 파일이 지키는 명제는 하나다.
**LLM 은 그래프를 채우고, 판정은 그래프 위의 룰이 한다.**
그래서 여기서 검사하는 것은 "판정이 잘 맞나" 보다 "판정 권한이 새지 않나" 다.
"""

from __future__ import annotations

import pytest

from llmwiki.compliance import analysis, changeset as cs, propose, rules, verify
from llmwiki.compliance.ontology import DEFERRED, SATISFIED, UNSATISFIED, node_id
from llmwiki.compliance.seed import RULESET_VERSION, seed
from llmwiki.compliance.spans import Span
from llmwiki.compliance.store import Store


@pytest.fixture(scope="module")
def store(tmp_path_factory) -> Store:
    s = Store(tmp_path_factory.mktemp("compliance"))
    seed(s)
    return s


@pytest.fixture(scope="module")
def graph(store: Store):
    return store.approved()


def verdicts(store: Store, **kw) -> dict[tuple[str, str], rules.Assessment]:
    g = kw.pop("graph", None) or store.approved()
    results = rules.adjudicate_all(
        g, ruleset_version=RULESET_VERSION, metrics=store.metrics, **kw)
    return {(a.service_uuid, a.control_code): a for a in results}


# --------------------------------------------------------------------------- #
# 저장소 — 삭제 없음 · 승인본/제안본 분리 · 재현성
# --------------------------------------------------------------------------- #
def test_seeded_graph_conforms_to_the_schema(store, graph):
    result = verify.validate_graph(graph, documents=store.documents())
    assert result.ok, "\n".join(str(i) for i in result.errors)


def test_journal_has_no_delete_operation(store):
    assert verify.validate_journal(store).ok
    ops = {rec.get("op") for rec in store.read_journal()}
    assert ops <= {"upsert", "obsolete"}


def test_approved_graph_never_contains_staging_nodes(graph):
    assert not [n for n in graph.nodes.values() if n["type"] in ("ChangeSet", "RegChange")]


def test_pending_proposals_do_not_touch_the_approved_graph(store):
    """제안이 아무리 쌓여도 판정은 흔들리지 않는다 — Flagged Revisions 구조."""
    before = store.approved()
    before_verdicts = verdicts(store, graph=before)
    cs.stage(
        store,
        [cs.create_node("Control", {"code": "ZZ-99", "title": "미승인 통제",
                                    "auto_level": "L1"})],
        proposer={"type": "Person", "id": "tester"},
    )
    after = store.approved()
    assert node_id("Control", code="ZZ-99") not in after.nodes
    assert len(after.nodes) == len(before.nodes)
    assert verdicts(store, graph=after) .keys() == before_verdicts.keys()


def test_as_of_reproduces_a_past_graph(store):
    """1년 뒤에도 당시 판정을 재현할 수 있어야 한다."""
    full = store.approved()
    early = store.approved(upto_seq=12)
    assert len(early.nodes) < len(full.nodes)
    assert store.approved(upto_seq=12).to_dict() == early.to_dict()


def test_obsolete_keeps_the_node_and_marks_it(store):
    work = Store(store.root)
    target = node_id("Evidence", uuid="req-risk-review-log")
    change = cs.stage(
        work, [cs.obsolete_node(target, replaced_by=node_id("Evidence", uuid="req-risk-review-report"))],
        proposer={"type": "Person", "id": "gov-officer"},
    )
    cs.approve(work, change.changeset_id, approver="gov-officer")
    g = work.approved()
    assert target in g.nodes                      # 사라지지 않는다
    assert g.nodes[target]["status"] == "obsolete"
    assert g.nodes[target]["props"]["replaced_by"]
    # 되돌린다 — 이후 테스트가 시드 상태를 그대로 보게 한다
    cs.approve(
        work,
        cs.stage(work, [cs.create_node("Evidence", {
            "uuid": "req-risk-review-log", "title": "위험 점검 이력",
            "evidence_kind": "점검이력", "required_yn": True, "status": "active",
            "replaced_by": "",
        })], proposer={"type": "Person", "id": "gov-officer"}).changeset_id,
        approver="gov-officer",
    )
    assert work.approved().nodes[target]["status"] == "active"


# --------------------------------------------------------------------------- #
# 커밋 결재 (L6)
# --------------------------------------------------------------------------- #
def test_physical_delete_is_forbidden(store, graph):
    ops = [{"op": "node.delete", "id": node_id("Control", code="ACC-01")}]
    assert cs.grade_of(graph, ops) == cs.FORBIDDEN
    change = cs.stage(store, ops, proposer={"type": "Person", "id": "tester"})
    assert change.status == cs.BLOCKED
    with pytest.raises(ValueError):
        cs.approve(store, change.changeset_id, approver="tester")


def test_new_node_is_g2_and_threshold_change_is_g3(store, graph):
    new_node = [cs.create_node("Control", {"code": "NEW-1", "title": "신규",
                                           "auto_level": "L1"})]
    assert cs.grade_of(graph, new_node) == cs.G2

    threshold = [cs.create_node("TestProcedure", {
        "control_code": "PRF-02", "seq": "2", "kind": "metric",
        "metric": "model_auc", "operator": ">=", "threshold": 0.90})]
    assert cs.grade_of(graph, threshold) == cs.G3
    assert cs.impact_of(graph, threshold)["breaking"] is True


def test_label_touch_up_is_g1(store, graph):
    ops = [cs.create_node("Control", {"code": "ACC-01", "title": "이해관계자 책임관계 문서",
                                      "auto_level": "L1", "note": "표기 정리"})]
    assert cs.grade_of(graph, ops) == cs.G1
    assert cs.impact_of(graph, ops)["breaking"] is False


def test_ruleset_change_is_g4(store, graph):
    ops = [cs.create_node("RuleSet", {"version": "2.0.0", "name": "차기 룰셋"})]
    assert cs.grade_of(graph, ops) == cs.G4


def test_impact_is_computed_before_merge(store, graph):
    ops = [cs.create_node("TestProcedure", {
        "control_code": "PRF-02", "seq": "2", "kind": "metric",
        "metric": "model_auc", "operator": ">=", "threshold": 0.99})]
    impact = cs.impact_of(graph, ops)
    assert impact["affected_control_codes"] == ["PRF-02"]
    assert impact["affected_services"] >= 2      # PRF-02 은 두 서비스에 적용돼 있다


def test_slm_cannot_propose_a_judgement(store, graph):
    """권한 3분할 — 모델은 판정 노드를 만들 수 없다."""
    ops = [cs.create_node("Assessment", {
        "uuid": "fake", "service_uuid": "svc-credit-scoring", "control_code": "ACC-01",
        "verdict": "SATISFIED", "versions": {}, "assessed_at": "2026-08-17"})]
    result = verify.validate_ops(graph, ops, proposer_kind="SoftwareAgent")
    assert any(i.code == "authority.propose" for i in result.errors)
    change = cs.stage(store, ops, proposer={"type": "SoftwareAgent", "id": "slm"})
    assert change.status == cs.BLOCKED


def test_a_person_may_register_a_judgement_but_the_model_may_not(graph):
    ops = [cs.create_node("Service", {"uuid": "svc-003", "name": "사람이 등록"})]
    assert verify.validate_ops(graph, ops, proposer_kind="Person").ok
    assert not verify.validate_ops(graph, ops, proposer_kind="SoftwareAgent").ok


def test_proposal_without_evidence_span_is_blocked(store, graph):
    ops = [cs.create_node("Obligation", {
        "uuid": "obl-nospan", "title": "근거 없는 의무", "level": "mandatory"})]
    result = verify.validate_ops(graph, ops, proposer_kind="SoftwareAgent")
    assert any(i.code == "span.required" for i in result.errors)


def test_hallucinated_citation_is_blocked(store, graph):
    """원문에 없는 문장을 근거로 단 제안은 사람 앞에 가지 못한다."""
    fake = Span(doc_id="ai-risk-guideline-2026", start=0, end=30,
                quote="금융회사는 모든 모형을 외부 기관의 검증을 받아야 한다")
    ops = [cs.create_node("Obligation", {
        "uuid": "obl-fake", "title": "외부 검증 의무", "level": "mandatory"},
        spans=[fake.to_dict()])]
    change = cs.stage(store, ops, proposer={"type": "SoftwareAgent", "id": "slm"})
    assert change.status == cs.BLOCKED
    assert any(i["code"] == "span.mismatch" for i in change.checks["issues"])


def test_overclaiming_a_recommendation_as_mandatory_is_blocked(store, graph):
    text = store.document("ai-risk-guideline-2026")
    quote = "금융회사는 성능지표의 산출 근거를 이용자에게 공개하도록 노력하여야 한다."
    start = text.find(quote)
    assert start >= 0
    span = Span.of("ai-risk-guideline-2026", text, start, start + len(quote))
    ops = [cs.create_node("Obligation", {
        "uuid": "obl-overclaim", "title": "산출 근거 공개 의무", "level": "mandatory"},
        spans=[span.to_dict()])]
    change = cs.stage(store, ops, proposer={"type": "SoftwareAgent", "id": "slm"})
    assert change.status == cs.BLOCKED
    assert any(i["code"] == "citation.force" for i in change.checks["issues"])
    # 같은 근거로 '권고' 라고 주장하면 통과한다
    ops[0]["props"]["level"] = "recommended"
    ok = cs.stage(store, ops, proposer={"type": "SoftwareAgent", "id": "slm"})
    assert ok.status == cs.PENDING


def test_dangling_edge_proposal_is_blocked(store, graph):
    ops = [cs.create_edge("IMPLEMENTED_BY", node_id("Obligation", uuid="ghost"),
                          node_id("Control", code="ACC-01"))]
    assert any(i.code == "edge.dangling"
               for i in verify.validate_ops(graph, ops).errors)


def test_edge_range_is_enforced(graph):
    ops = [cs.create_edge("PRODUCES", node_id("Control", code="ACC-01"),
                          node_id("Service", uuid="svc-credit-scoring"))]
    assert any(i.code == "edge.range" for i in verify.validate_ops(graph, ops).errors)


def test_blocked_proposal_cannot_be_approved(store, graph):
    change = cs.stage(store, [cs.create_node("Obligation", {
        "uuid": "obl-blocked", "title": "근거 없음", "level": "mandatory"})],
        proposer={"type": "SoftwareAgent", "id": "slm"})
    assert change.status == cs.BLOCKED
    with pytest.raises(ValueError):
        cs.approve(store, change.changeset_id, approver="gov-officer")


def test_rejection_keeps_the_history(store, graph):
    change = cs.stage(store, [cs.create_node("Control", {
        "code": "TMP-1", "title": "임시", "auto_level": "L1"})],
        proposer={"type": "Person", "id": "tester"})
    cs.reject(store, change.changeset_id, reviewer="gov-officer", note="범위 밖")
    assert store.changeset(change.changeset_id)["status"] == cs.REJECTED
    ids = [r["changeset_id"] for r in store.changeset_history()]
    assert ids.count(change.changeset_id) >= 2     # 제안과 반려가 모두 남는다
    assert node_id("Control", code="TMP-1") not in store.approved().nodes


# --------------------------------------------------------------------------- #
# 판정 (L3)
# --------------------------------------------------------------------------- #
def test_evidence_present_signed_and_valid_is_satisfied(store):
    a = verdicts(store)[("svc-credit-scoring", "ACC-01")]
    assert a.verdict == SATISFIED
    assert a.have == a.need == 1
    assert a.evidence_ids


def test_missing_evidence_is_unsatisfied(store):
    assert verdicts(store)[("svc-credit-scoring", "CHG-04")].verdict == UNSATISFIED


def test_partial_evidence_is_deferred_not_guessed(store):
    a = verdicts(store)[("svc-credit-scoring", "RSK-03")]
    assert a.verdict == DEFERRED
    assert a.raw_verdict == "PARTIAL"
    assert "PARTIAL_EVIDENCE" in a.triggers


def test_qualitative_control_is_never_auto_decided(store):
    a = verdicts(store)[("svc-credit-scoring", "EXP-06")]
    assert a.verdict == DEFERRED
    assert "QUALITATIVE" in a.triggers


def test_undefined_threshold_defers_instead_of_failing(store):
    a = verdicts(store)[("svc-credit-scoring", "DRF-05")]
    assert a.verdict == DEFERRED
    assert "THRESHOLD_UNDEFINED" in a.triggers


def test_expiring_evidence_defers(store):
    a = verdicts(store)[("svc-call-summary", "PRF-02")]
    assert a.verdict == DEFERRED
    assert "EVIDENCE_EXPIRING" in a.triggers


def test_metric_is_compared_deterministically(store):
    a = verdicts(store)[("svc-credit-scoring", "PRF-02")]
    assert a.verdict == SATISFIED
    assert "model_auc 0.82 >= 0.75 충족" in a.reason


def test_metric_below_threshold_is_unsatisfied(store, graph):
    low = {"svc-credit-scoring": {"model_auc": 0.60}}
    a = rules.adjudicate(graph, "svc-credit-scoring", "PRF-02", metrics=low,
                         ruleset_version=RULESET_VERSION)
    assert a.raw_verdict in ("PARTIAL", "UNSATISFIED")
    assert a.verdict != SATISFIED


def test_control_not_applied_is_not_applicable(graph):
    # RSK-03(연차 위험 점검)은 고영향 서비스에만 적용된다 — 콜센터에는 붙지 않는다
    a = rules.adjudicate(graph, "svc-call-summary", "RSK-03", ruleset_version=RULESET_VERSION)
    assert a.verdict == "NOT_APPLICABLE"


def test_unsigned_evidence_does_not_count(store, graph):
    g = graph.copy()
    g.nodes[node_id("Evidence", uuid="evd-acc-credit")]["props"]["sign_yn"] = False
    a = rules.adjudicate(g, "svc-credit-scoring", "ACC-01", ruleset_version=RULESET_VERSION)
    assert a.verdict == UNSATISFIED
    assert "서명 없음" in a.reason


def test_expired_evidence_does_not_count(store, graph):
    g = graph.copy()
    g.nodes[node_id("Evidence", uuid="evd-acc-credit")]["props"]["valid_to"] = "2020-01-01"
    a = rules.adjudicate(g, "svc-credit-scoring", "ACC-01", ruleset_version=RULESET_VERSION)
    assert a.verdict == UNSATISFIED
    assert "유효기간 만료" in a.reason


def test_amending_provision_defers_everything_downstream(store, graph):
    g = graph.copy()
    for node in g.of_type("Provision"):
        if "책임관계" in str(node["props"].get("text", "")):
            node["props"]["status"] = "amending"
    a = rules.adjudicate(g, "svc-credit-scoring", "ACC-01", ruleset_version=RULESET_VERSION)
    assert a.verdict == DEFERRED
    assert "PROVISION_AMENDING" in a.triggers


def test_flipped_verdict_defers_for_review(graph):
    a = rules.adjudicate(graph, "svc-credit-scoring", "ACC-01", ruleset_version=RULESET_VERSION,
                         prior={"ACC-01": UNSATISFIED})
    assert a.verdict == DEFERRED
    assert "VERDICT_FLIPPED" in a.triggers


def test_every_assessment_records_four_versions(store):
    for a in verdicts(store).values():
        assert set(a.versions) == {"ontology", "ruleset", "standard", "provisions"}
        assert a.versions["ontology"] and a.versions["ruleset"]


def test_adjudication_is_deterministic(store, graph):
    first = rules.adjudicate_all(graph, ruleset_version=RULESET_VERSION,
                                 metrics=store.metrics, today="2026-08-17")
    second = rules.adjudicate_all(graph, ruleset_version=RULESET_VERSION,
                                  metrics=store.metrics, today="2026-08-17")
    assert [a.to_props() | {"assessed_at": ""} for a in first] == \
           [a.to_props() | {"assessed_at": ""} for a in second]


def test_precision_first_defers_rather_than_guesses(store):
    """유보가 있는 만큼 커버리지는 내려가지만, 판정한 것은 틀리지 않는다."""
    metrics = verify.audit_metrics(list(verdicts(store).values()))
    assert 0.3 <= metrics["auto_rate"] <= 0.8
    assert metrics["deferred"] > 0


# --------------------------------------------------------------------------- #
# 확정 서명 (게이트 3)
# --------------------------------------------------------------------------- #
def test_confirmation_is_required_and_recorded(tmp_path):
    work = Store(tmp_path / "confirm")
    seed(work)
    results = rules.adjudicate_all(work.approved(), ruleset_version=RULESET_VERSION,
                                   metrics=work.metrics)
    rules.commit(work, results, ruleset_version=RULESET_VERSION)
    target = next(a for a in results if a.control_code == "ACC-01")

    graph = work.approved()
    node = graph.node(node_id("Assessment", uuid=target.uuid))
    assert node["props"]["decision_status"] == "provisional"
    assert node["derivation"] == "rule"

    props = rules.confirm(work, target.uuid, agent_id="gov-officer")
    assert props["decision_status"] == "confirmed"
    after = work.approved().node(node_id("Assessment", uuid=target.uuid))
    assert after["derivation"] == "rule"          # 값을 바꾸지 않았으므로 여전히 룰

    other = next(a for a in results if a.control_code == "RSK-03")
    rules.confirm(work, other.uuid, agent_id="gov-officer", verdict="PARTIAL")
    flipped = work.approved().node(node_id("Assessment", uuid=other.uuid))
    assert flipped["props"]["verdict"] == "PARTIAL"
    assert flipped["derivation"] == "human"       # 사람이 뒤집었으면 근거는 사람이다


def test_committed_assessments_carry_prov_lineage(tmp_path):
    work = Store(tmp_path / "prov")
    seed(work)
    results = rules.adjudicate_all(work.approved(), ruleset_version=RULESET_VERSION,
                                   metrics=work.metrics)
    rules.commit(work, results, ruleset_version=RULESET_VERSION)
    g = work.approved()
    target = next(a for a in results if a.control_code == "ACC-01")
    asmt = node_id("Assessment", uuid=target.uuid)
    assert g.targets(asmt, "used")                        # 무엇을 근거로 삼았나
    assert g.targets(asmt, "wasAttributedTo")             # 누가 냈나
    assert g.sources(asmt, "ASSESSED_AS")                 # 어느 서비스의 판정인가
    assert verify.validate_graph(g, documents=work.documents()).ok


# --------------------------------------------------------------------------- #
# 골드셋 · 분석
# --------------------------------------------------------------------------- #
def test_goldset_passes_with_honest_coverage(store, graph):
    report = verify.run_goldset(graph, store.goldset, metrics=store.metrics,
                                ruleset_version=RULESET_VERSION)
    assert report.passed, report.misses
    assert report.precision == 1.0
    assert 0.3 <= report.coverage <= 0.8     # 유보한 만큼 커버리지가 내려간다
    assert report.deferred > 0


def test_cohen_kappa_math():
    assert verify.cohen_kappa([("A", "A"), ("B", "B")]) == 1.0
    assert verify.cohen_kappa([("A", "B"), ("B", "A")]) < 0.0
    assert verify.cohen_kappa([]) == 0.0


def test_coverage_gap_finds_uncontrolled_obligations(graph):
    gap = analysis.coverage_gap(graph)
    assert gap["summary"]["uncovered"] >= 1
    # 제10조(인적 감독)에는 대응 통제를 두지 않았다 — 갭 분석이 이걸 잡아야 한다
    assert any(
        "인적 감독" in row["title"] for row in gap["uncovered_obligations"]
    )


def test_manual_controls_are_flagged_as_automation_candidates(graph):
    gap = analysis.coverage_gap(graph)
    assert [row["control"] for row in gap["manual_controls"]] == ["CHG-04"]


def test_provision_impact_reaches_services(graph):
    provision = next(
        n for n in graph.of_type("Provision")
        if "책임관계" in str(n["props"].get("text", ""))
    )
    impact = analysis.provision_impact(graph, provision["props"]["uuid"])
    assert impact["controls"] == ["ACC-01"]
    assert "여신심사 스코어링" in impact["services"]


# --------------------------------------------------------------------------- #
# LLMWiki 연계
# --------------------------------------------------------------------------- #
def test_llmwiki_programs_become_system_functions():
    """운영 소스에서 뽑은 프로그램이 증적 생산 기능으로 이어진다."""
    from llmwiki.config import load_config
    from llmwiki.indexer import scan
    from pathlib import Path

    idx = scan(load_config(Path(__file__).resolve().parents[1] / "config.yaml"))
    result = propose.propose_system_functions(idx, project_id="default")
    assert result.ops
    props = result.ops[0]["props"]
    assert props["program_ref"].startswith("prog:default/")
    assert props["key"].startswith("llmwiki:")
    assert all(op["op"] == "node.create" for op in result.ops)


def test_baseline_extractor_never_invents_a_quote(store):
    """LLM 없이 돌려도 근거 대조를 똑같이 거친다."""
    g = store.approved()
    provisions = g.of_type("Provision")
    result = propose.propose_obligations(store, provisions)
    documents = store.documents()
    for op in result.ops:
        for span in op.get("spans", []):
            text = documents[span["doc_id"]]
            assert text[span["start"]:span["end"]] == span["quote"]
