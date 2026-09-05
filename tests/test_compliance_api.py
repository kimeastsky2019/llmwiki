"""규제 API — 읽기는 승인본만, 쓰기는 결재 경로만.

API 로 그래프에 직접 쓸 수 있으면 커밋 결재가 우회된다. 그 구멍이 없다는 것을
여기서 고정한다.
"""

from __future__ import annotations

import os

import pytest

import llmwiki.compliance.seed as seed_mod
from fastapi.testclient import TestClient

from llmwiki.compliance import analysis
from llmwiki.compliance import changeset as cs
from llmwiki.compliance.seed import seed
from llmwiki.compliance.store import Store

CONFIG = """
project:
  name: "규제 API 테스트"
  source_roots: ["{root}/sample"]
compliance:
  dir: "{data}"
  ruleset: "1.0.0"
  standard: "2026.08"
output:
  docs_dir: "{data}/docs"
  index_file: "{data}/docs/index.json"
"""


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from pathlib import Path

    data = tmp_path_factory.mktemp("regapi")
    seed(Store(data))
    cfg_path = data / "config.yaml"
    cfg_path.write_text(
        CONFIG.format(root=Path(__file__).resolve().parents[1], data=data),
        encoding="utf-8",
    )
    # 서버 모듈은 임포트 시점에 설정을 읽는다. 이 테스트만 다른 설정을 보게 하고,
    # 끝나면 원래대로 되돌린다 — 안 그러면 뒤따르는 테스트가 이 설정을 물려받는다.
    import importlib

    import llmwiki.server.app as app_module

    previous = os.environ.get("LLMWIKI_CONFIG")
    os.environ["LLMWIKI_CONFIG"] = str(cfg_path)
    importlib.reload(app_module)
    try:
        with TestClient(app_module.app) as c:
            yield c
    finally:
        if previous is None:
            os.environ.pop("LLMWIKI_CONFIG", None)
        else:
            os.environ["LLMWIKI_CONFIG"] = previous
        importlib.reload(app_module)


def test_schema_and_graph(client):
    assert client.get("/api/reg/schema").json()["ontology"] == "1.1.0"
    graph = client.get("/api/reg/graph").json()
    assert graph["counts"]["Control"] == len(seed_mod.CONTROLS)
    # 시드는 결재 대기 1건을 일부러 남긴다 (승인 화면이 보여 줄 것이 있어야 한다).
    # 중요한 것은 개수가 아니라 **승인 전 제안이 승인 그래프에 없다**는 것이다.
    assert graph["pending_changes"] == 1
    assert "HUM-09" not in client.get("/api/reg/nodes?type=Control").text


def test_validate_is_clean(client):
    payload = client.get("/api/reg/validate").json()
    assert payload["ok"], payload["issues"]


def test_assess_returns_deterministic_verdicts(client):
    first = client.get("/api/reg/assess?today=2026-08-17").json()
    second = client.get("/api/reg/assess?today=2026-08-17").json()
    assert first["metrics"] == second["metrics"]
    assert [a["verdict"] for a in first["assessments"]] == \
           [a["verdict"] for a in second["assessments"]]
    assert first["metrics"]["deferred"] > 0


def test_goldset_reports_coverage_and_precision(client):
    report = client.get("/api/reg/goldset").json()
    assert report["result"] == "PASS"
    assert report["precision"] == 1.0
    assert report["coverage"] < 1.0


def test_coverage_gap_endpoint(client):
    gap = client.get("/api/reg/coverage").json()
    assert gap["summary"]["uncovered"] >= 1


def test_there_is_no_endpoint_that_writes_the_graph_directly():
    """승인 그래프를 움직이는 길은 결재와 확정 서명뿐이다.

    노드를 직접 만들거나 지우는 엔드포인트가 생기면 커밋 결재가 우회된다.
    새 쓰기 경로를 열려면 이 목록을 먼저 고쳐야 한다 — 의도적인 마찰이다.
    """
    from llmwiki.server.compliance import router

    writable = {
        route.path
        for route in router.routes
        if {"POST", "PUT", "PATCH", "DELETE"} & set(getattr(route, "methods", set()))
    }
    assert writable == {
        "/api/reg/assess/commit",
        "/api/reg/assess/{assessment_uuid}/confirm",
        "/api/reg/changes/{changeset_id}/approve",
        "/api/reg/changes/{changeset_id}/reject",
        # 위험등급 산정은 승인 그래프를 건드리지 않는다. 계산(assess)과
        # 작성 중인 평가지 저장(draft)뿐이고, 별도 파일에만 쓴다.
        "/api/reg/risk/assess",
        "/api/reg/risk/draft/{service_uuid}",
        # 조언은 읽기만 한다 — LLM 에 물어보고 결과를 돌려줄 뿐 아무것도 쓰지 않는다.
        # POST 인 것은 본문에 코드 분석 사실을 실어 보내기 때문이다.
        "/api/reg/risk/advise",
        # 서비스 정의도 그래프에 직접 쓰지 않는다. ChangeSet 을 만들어 결재 큐에
        # 올릴 뿐이고, 승인돼야 저널에 들어간다 — 아래 테스트가 그것을 확인한다.
        "/api/reg/services/propose",
        # 코드 근거 제안은 아무것도 쓰지 않는다. 조언과 같은 이유로 POST 다.
        "/api/reg/risk/suggest",
        # 관리자가 만든 평가 항목·지표도 그래프에 직접 쓰지 않는다. 서비스 정의와
        # 같은 길로 ChangeSet 이 되어 결재 큐에 올라갈 뿐이다. 기준을 만드는 일은
        # 결재를 건너뛰면 안 되는 쪽이다 — 통제 하나가 바뀌면 그 통제를 쓰는
        # 모든 서비스의 판정이 바뀐다.
        "/api/reg/controls/propose",
        # 프로젝트 결재 — 승인 그래프를 건드리지 않는다. 별도 append-only 파일
        # (approvals.jsonl)에만 쌓인다. 기준 변경 결재(/changes)와 다른 축이라
        # 한 테이블에 합치지 않았다 — 합치면 "기준이 바뀌었다" 와 "서비스가
        # 승인됐다" 가 같은 줄에 서서 감사에서 답이 섞인다.
        "/api/reg/approvals",
        "/api/reg/approvals/{approval_id}/decide",
        "/api/reg/approvals/{approval_id}/verify",
        # 기획 도우미는 읽기만 한다 — 조언과 같은 이유로 POST 다(본문에 대화를 싣는다).
        "/api/reg/assist",
        # 데이터 분석은 올린 파일을 임시 폴더에서만 읽고 지운다. 그래프에도,
        # 저장소에도 쓰지 않는다 — 원본을 남기려면 보존기간과 파기 절차부터
        # 정해야 하고 지금은 그 결정이 없다.
        "/api/reg/data/analyze",
    }


def test_risk_endpoints_do_not_touch_the_graph(client):
    """위험등급 산정이 그래프 저널을 건드리지 않는다는 것을 실제로 확인한다."""
    before = client.get("/api/reg/graph").json()["seq"]
    client.post("/api/reg/risk/assess", json={"items": [{"no": 1, "identified": True}]})
    client.post("/api/reg/risk/draft/svc-guard",
                json={"by": "tester", "input": {"items": []}})
    after = client.get("/api/reg/graph").json()["seq"]
    assert after == before
    client.delete("/api/reg/risk/draft/svc-guard")


def test_pending_proposal_is_visible_but_not_applied(client, tmp_path_factory):
    store = Store(client.app.state.compliance_root)
    change = cs.stage(
        store,
        [cs.create_node("Control", {"code": "API-1", "title": "API 제안",
                                    "auto_level": "L1"})],
        proposer={"type": "Person", "id": "tester"},
    )
    listed = client.get("/api/reg/changes?status=pending_review").json()["changes"]
    assert any(c["changeset_id"] == change.changeset_id for c in listed)
    assert client.get("/api/reg/node/ctrl:API-1").status_code == 404

    detail = client.get(f"/api/reg/changes/{change.changeset_id}").json()
    assert detail["grade"] == "G2"
    assert detail["diff"]["added_nodes"]

    approved = client.post(f"/api/reg/changes/{change.changeset_id}/approve",
                           json={"by": "gov-officer"}).json()
    assert approved["status"] == "approved"
    assert client.get("/api/reg/node/ctrl:API-1").status_code == 200


def test_approval_requires_an_approver(client):
    assert client.post("/api/reg/changes/nope/approve", json={}).status_code == 400


def test_confirm_requires_a_signer(client):
    assert client.post("/api/reg/assess/x/confirm", json={}).status_code == 400


# --------------------------------------------------------------------------- #
# 언어 전환
#
# 이 화면이 어색했던 원인이 정확히 여기였다 — API 가 lang 을 무시해서, 화면을
# 영어로 바꿔도 판정 라벨과 사유는 한국어로 나왔다. 한 행에 두 언어가 섞였다.
# --------------------------------------------------------------------------- #
def test_assess_follows_the_requested_language(client):
    ko = client.get("/api/reg/assess?lang=ko").json()
    en = client.get("/api/reg/assess?lang=en").json()

    assert ko["verdict_labels"]["SATISFIED"] == "충족"
    assert en["verdict_labels"]["SATISFIED"] == "Satisfied"

    def row(payload, code):
        return next(a for a in payload["assessments"] if a["control_code"] == code)

    ko_row, en_row = row(ko, "ACC-01"), row(en, "ACC-01")
    # 판정 자체는 언어와 무관하다 — 바뀌는 것은 표시뿐이다.
    assert ko_row["verdict"] == en_row["verdict"]
    assert ko_row["label"] != en_row["label"]
    assert "룰 판정" in ko_row["reason"]
    assert "Rule verdict" in en_row["reason"]
    # 서비스·통제 이름도 따라간다 (한국어가 원본, _en 이 별칭)
    assert ko_row["service_name"] != en_row["service_name"]


def test_language_does_not_change_the_verdict(client):
    ko = {(a["service_uuid"], a["control_code"]): a["verdict"]
          for a in client.get("/api/reg/assess?lang=ko").json()["assessments"]}
    en = {(a["service_uuid"], a["control_code"]): a["verdict"]
          for a in client.get("/api/reg/assess?lang=en").json()["assessments"]}
    assert ko == en


def test_schema_and_coverage_follow_the_language(client):
    ko = client.get("/api/reg/schema?lang=ko").json()["deferral_triggers"]
    en = client.get("/api/reg/schema?lang=en").json()["deferral_triggers"]
    assert "정성 판단" in ko["QUALITATIVE"]
    assert "human judgement" in en["QUALITATIVE"]

    ko_gap = client.get("/api/reg/coverage?lang=ko").json()
    en_gap = client.get("/api/reg/coverage?lang=en").json()
    assert ko_gap["summary"] == en_gap["summary"]
    if ko_gap["manual_controls"]:
        assert "수기 의존" in ko_gap["manual_controls"][0]["note"]
        assert "manual today" in en_gap["manual_controls"][0]["note"]


def test_unknown_language_falls_back_instead_of_blanking(client):
    payload = client.get("/api/reg/assess?lang=zz").json()
    assert payload["verdict_labels"]["SATISFIED"] == "충족"


# --------------------------------------------------------------------------- #
# AI 위험등급 산정 API (STEP 1~5)
# --------------------------------------------------------------------------- #
def test_risk_master_is_served_and_intact(client):
    m = client.get("/api/reg/risk/master").json()
    assert len(m["items"]) == 32
    assert sum(int(r["points"]) for r in m["items"]) == 100
    assert m["invariant_problems"] == []
    # 기술 임계값은 참고값이라는 것이 응답에 드러나야 한다
    assert m["technical_thresholds"]["scored"] is False
    # 4축 매핑은 원본 미확정 — 화면이 '작성 안내'로만 쓰도록 알려 준다
    assert m["evaluation_set"]["mapping_defined"] is False


def test_risk_assess_runs_the_pipeline(client):
    res = client.post("/api/reg/risk/assess", json={
        "high_impact_a": ["A1"], "high_impact_b": ["B1", "B2"],
        "safety": {"S1": True, "S2": True, "S3": True},
        "items": [{"no": 27, "identified": True, "mitigated": True, "residual": "△"}],
    }).json()
    assert res["step1_high_impact"]["high_impact"] is True
    assert res["step1_safety"]["safety_target"] is True
    assert res["step4_residual_score"] == 4.0
    assert res["final_grade"]["label"] == "고위험 서비스"   # 고영향 오버라이드
    assert res["final_grade"]["override_applied"] is True
    assert res["assessed_at"]


def test_risk_assess_is_deterministic(client):
    body = {"high_impact_a": ["A1", "A2"],
            "items": [{"no": 10, "identified": True, "mitigated": False}]}
    a = client.post("/api/reg/risk/assess", json=body).json()
    b = client.post("/api/reg/risk/assess", json=body).json()
    for key in ("step3_recognized_score", "step4_residual_score"):
        assert a[key] == b[key]
    assert a["final_grade"]["key"] == b["final_grade"]["key"]


def test_risk_draft_save_load_and_delete(client):
    saved = client.post("/api/reg/risk/draft/svc-credit-scoring", json={
        "by": "gov-officer",
        "input": {
            "service_name": "여신심사 스코어링",
            "high_impact_a": ["A1", "A2"],
            "items": [{"no": 1, "identified": True, "mitigated": True, "residual": "△"}],
        },
    }).json()
    # 입력과 결과를 함께 남긴다 — 룰이 바뀌어도 그때 무엇을 눌렀는지 남아야 한다
    assert saved["saved_by"] == "gov-officer"
    assert saved["input"]["service_uuid"] == "svc-credit-scoring"
    assert saved["result"]["final_grade"]["label"] == "고위험 서비스"

    drafts = client.get("/api/reg/risk/drafts").json()["drafts"]
    assert [d["service_uuid"] for d in drafts] == ["svc-credit-scoring"]
    assert drafts[0]["high_impact"] is True

    got = client.get("/api/reg/risk/draft/svc-credit-scoring").json()
    assert got["result"]["step4_residual_score"] == 2.0

    assert client.delete("/api/reg/risk/draft/svc-credit-scoring").json()["removed"] is True
    assert client.get("/api/reg/risk/drafts").json()["drafts"] == []


def test_risk_draft_requires_a_signer(client):
    res = client.post("/api/reg/risk/draft/svc-x", json={"input": {}})
    assert res.status_code == 400


def test_missing_risk_draft_is_404(client):
    assert client.get("/api/reg/risk/draft/nope").status_code == 404


def test_advice_endpoint_writes_nothing(client):
    """조언은 그래프도 평가지도 건드리지 않는다."""
    before_seq = client.get("/api/reg/graph").json()["seq"]
    before_drafts = client.get("/api/reg/risk/drafts").json()["drafts"]
    res = client.post("/api/reg/risk/advise",
                      json={"item_no": 5, "stage": "identify"})
    assert res.status_code == 200
    body = res.json()
    # 공급자가 없는 테스트 환경에서도 예외가 아니라 error 필드로 돌아온다
    assert "error" in body and body["derivation"] == "llm"
    # 판정 자리가 없다
    for forbidden in ("verdict", "identified", "score", "grade"):
        assert forbidden not in body
    assert client.get("/api/reg/graph").json()["seq"] == before_seq
    assert client.get("/api/reg/risk/drafts").json()["drafts"] == before_drafts


def test_advice_rejects_a_bad_stage(client):
    res = client.post("/api/reg/risk/advise", json={"item_no": 1, "stage": "decide"})
    assert res.status_code == 400


def test_advisors_endpoint_marks_local_vs_external(client):
    body = client.get("/api/reg/risk/advisors").json()
    assert "advisors" in body
    for a in body["advisors"]:
        assert isinstance(a["local"], bool)
        assert "ready" in a


# --------------------------------------------------------------------------- #
# 서비스 — 코드 분석과 규제 검증이 붙는 자리
#
# 여기 있는 테스트가 지키는 것은 기능이 아니라 경계다. 두 갈래를 이어도
# "제안 / 판정 / 확정" 분리가 그대로여야 한다 — 자동화한 만큼 감리에서
# 되돌려 받지 않으려면 이 선이 코드에서 강제돼야 한다.
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def indexed(client):
    """샘플 소스를 분석해 인덱스를 만든다. 서비스 정의의 전제 조건이다."""
    from llmwiki.indexer import save_index, scan
    from llmwiki.server.app import registry

    cfg = registry.config_for(registry.get(None))
    save_index(cfg, scan(cfg))
    return client


def test_programs_are_offered_as_service_candidates(indexed):
    body = indexed.get("/api/reg/programs").json()
    assert body["programs"], "분석된 프로그램이 후보로 나와야 한다"
    row = body["programs"][0]
    assert {"id", "name", "layer", "tables", "urls", "services"} <= set(row)
    # 아직 어느 서비스에도 묶이지 않았다
    assert all(not p["services"] for p in body["programs"])


def test_service_definition_goes_through_the_approval_queue(indexed):
    """서비스 정의도 결재를 거친다 — 승인 전에는 그래프에 없다."""
    program_ids = [p["id"] for p in indexed.get("/api/reg/programs").json()["programs"]][:2]
    res = indexed.post("/api/reg/services/propose", json={
        "name": "여신 심사 보조", "program_ids": program_ids, "by": "gov-officer",
    })
    assert res.status_code == 200, res.text
    change = res.json()["changeset"]
    assert change["status"] == cs.PENDING
    assert change["proposer"]["type"] == "Person"

    # 승인 전: 승인 그래프에도, 서비스 목록에도 없다
    before = {s["uuid"] for s in indexed.get("/api/reg/services").json()["services"]}
    assert "svc-여신-심사-보조" not in before
    assert indexed.get("/api/reg/service/svc-여신-심사-보조").status_code == 404

    ok = indexed.post(f"/api/reg/changes/{change['changeset_id']}/approve",
                      json={"by": "ciso"})
    assert ok.status_code == 200, ok.text

    detail = indexed.get("/api/reg/service/svc-여신-심사-보조")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["service"]["programs"] == len(program_ids)
    assert {f["program_id"] for f in body["functions"]} == set(program_ids)
    # 등급이 아직 없으므로 다음 단계는 ③ 위험등급 산정이다
    assert body["stage"] == "grade"

    # 묶인 뒤에는 후보 목록이 그 사실을 보여 준다 — 같은 프로그램을 두 서비스에
    # 넣기 전에 사람이 알아야 한다.
    again = {p["id"]: p["services"] for p in
             indexed.get("/api/reg/programs").json()["programs"]}
    assert all("svc-여신-심사-보조" in again[pid] for pid in program_ids)


def test_an_slm_may_not_propose_a_service(indexed):
    """서비스 경계는 업무 판단이다. 모델이 제안하면 기계 검증에서 막힌다."""
    from llmwiki.compliance import propose as propose_mod
    from llmwiki.compliance.store import Store
    from llmwiki.server.app import cfg as server_cfg
    from llmwiki.indexer import load_index
    from llmwiki.server.app import registry

    idx = load_index(registry.config_for(registry.get(None)), with_source=False)
    result = propose_mod.propose_service(
        idx, name="모델이 지어낸 서비스",
        program_ids=[idx.programs[0].id],
    )
    change = cs.stage(Store(server_cfg.compliance_dir), result.ops,
                      proposer={"type": "SoftwareAgent", "id": "slm-extract-v1"})
    assert change.status == cs.BLOCKED
    codes = {i["code"] for i in change.checks["issues"]}
    assert "authority.propose" in codes


def test_code_hints_suggest_but_never_decide(indexed):
    """코드 근거는 제안이다. 신뢰도는 전부 후보이고, 못 답하는 것을 함께 말한다."""
    body = indexed.post("/api/reg/risk/suggest",
                        json={"service_uuid": "svc-여신-심사-보조"}).json()
    assert body["profile"], "프로파일 후보가 나와야 한다"
    assert all(p["confidence"] == "candidate" for p in body["profile"])
    assert all(i["confidence"] == "candidate" for i in body["items"])
    # 제안은 축 2개(사용자 범위·데이터 민감도)까지만 — 나머지는 코드에 없다
    assert {p["axis"] for p in body["profile"]} <= {"user_scope", "data_sensitivity"}
    unanswerable = {u["key"] for u in body["unanswerable"]}
    assert {"high_impact", "output_kind", "decision_impact"} <= unanswerable
    # 모든 제안에는 근거가 붙어 있다 — 근거 없는 제안은 내지 않는다
    assert all(p["evidence"] for p in body["profile"])
    assert all(i["evidence"] for i in body["items"])


def test_suggestion_never_writes_anything(indexed):
    before = indexed.get("/api/reg/graph").json()["counts"]
    indexed.post("/api/reg/risk/suggest", json={"service_uuid": "svc-여신-심사-보조"})
    assert indexed.get("/api/reg/graph").json()["counts"] == before


# --------------------------------------------------------------------------- #
# 평가 항목·지표 만들기 (관리자)
# --------------------------------------------------------------------------- #
def test_controls_list_shows_metric_and_its_basis(client):
    """기준 화면이 그리는 줄 — 지표·산식·임계치·근거 법규가 한 줄에 있다."""
    body = client.get("/api/reg/controls").json()
    by_code = {c["code"]: c for c in body["controls"]}

    prf = by_code["PRF-02"]
    metric = [p for p in prf["procedures"] if p["kind"] == "metric"][0]
    assert (metric["metric"], metric["operator"], metric["threshold"]) == ("model_auc", ">=", 0.75)
    assert prf["obligations"], "근거 법규가 되짚어져야 한다"
    assert prf["open_thresholds"] == 0

    # 임계치를 정하지 않은 지표는 그 사실이 세어져 나온다 — 관리자가 고칠 자리다
    assert by_code["DRF-05"]["open_thresholds"] == 1

    assert body["vocabulary"]["operator"] == [">=", ">", "<=", "<", "==", "!="]


def test_a_new_evaluation_item_goes_through_the_approval_queue(client):
    """관리자가 만든 평가 항목도 결재를 거친다 — 승인 전에는 기준이 아니다."""
    res = client.post("/api/reg/controls/propose", json={
        "by": "gov-officer",
        "code": "mon-11", "title": "승인율 격차 상시 감시",
        "auto_level": "L2", "category": "공정성", "owner": "리스크관리부",
        "procedures": [
            {"kind": "metric", "metric": "approval_gap", "operator": "<=",
             "threshold": 5.0, "unit": "%p"},
            {"kind": "evidence"},
        ],
    })
    assert res.status_code == 200, res.text
    change = res.json()["changeset"]
    assert change["status"] == cs.PENDING

    # 승인 전에는 기준 목록에 없다
    assert "MON-11" not in {c["code"] for c in client.get("/api/reg/controls").json()["controls"]}

    ok = client.post(f"/api/reg/changes/{change['changeset_id']}/approve", json={"by": "ciso"})
    assert ok.status_code == 200, ok.text

    row = {c["code"]: c for c in client.get("/api/reg/controls").json()["controls"]}["MON-11"]
    assert row["title"] == "승인율 격차 상시 감시"
    assert row["open_thresholds"] == 0
    metric = [p for p in row["procedures"] if p["kind"] == "metric"][0]
    assert (metric["metric"], metric["operator"], metric["threshold"]) == ("approval_gap", "<=", 5.0)


def test_a_half_written_threshold_is_refused(client):
    """연산자와 임계치는 짝이다. 한쪽만 있으면 판정이 불가능하니 되돌린다."""
    res = client.post("/api/reg/controls/propose", json={
        "by": "gov-officer", "code": "HALF-01", "title": "반쪽 임계치",
        "procedures": [{"kind": "metric", "metric": "x", "threshold": 1.0}],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rejected"], "되돌린 절차를 숨기지 않는다"
    assert "연산자" in body["rejected"][0]["reason"]
    # 통제는 만들되 반쪽짜리 지표만 뺀다 — 관리자가 나머지를 이어 쓸 수 있다
    ops = body["changeset"]["ops"]
    assert not [o for o in ops if o.get("node_type") == "TestProcedure"]


def test_an_undecided_threshold_is_allowed_and_stays_visible(client):
    """임계치 미정을 막지 않는다. 없는 것을 채우게 하면 그 숫자가 근거가 된다."""
    res = client.post("/api/reg/controls/propose", json={
        "by": "gov-officer", "code": "OPEN-01", "title": "임계치 미정 지표",
        "procedures": [{"kind": "metric", "metric": "fairness_gap"}],
    })
    assert res.status_code == 200, res.text
    assert not res.json()["rejected"]
    change = res.json()["changeset"]
    client.post(f"/api/reg/changes/{change['changeset_id']}/approve", json={"by": "ciso"})

    row = {c["code"]: c for c in client.get("/api/reg/controls").json()["controls"]}["OPEN-01"]
    assert row["open_thresholds"] == 1


def test_a_duplicate_control_code_is_refused(client):
    res = client.post("/api/reg/controls/propose", json={
        "by": "gov-officer", "code": "ACC-01", "title": "중복 코드",
    })
    assert res.status_code == 400
    assert "이미 있는" in res.json()["detail"]


def test_an_slm_may_draft_an_evaluation_item_but_not_enact_it(client):
    """모델이 기준을 **제안**하는 것은 막지 않는다 — `Control` 은 `llm_proposable=True`.

    서비스 경계(`Service`)와 다른 점이다. 서비스는 어디까지가 한 서비스인지가
    업무 판단이라 모델이 손댈 수 없지만, 통제 초안은 규정 문장에서 뽑아 올 수
    있는 것이라 제안 자체를 막을 이유가 없다.

    막는 자리는 그다음이다 — 승인 없이는 기준이 되지 않는다.
    """
    from llmwiki.compliance import propose as propose_mod
    from llmwiki.compliance.store import Store
    from llmwiki.server.app import cfg as server_cfg

    result = propose_mod.propose_control(code="SLM-99", title="모델이 초안 잡은 기준")
    change = cs.stage(Store(server_cfg.compliance_dir), result.ops,
                      proposer={"type": "SoftwareAgent", "id": "slm-extract-v1"})
    assert change.status == cs.PENDING
    assert change.proposer["type"] == "SoftwareAgent"
    # 상신됐을 뿐 기준 목록에는 없다
    assert "SLM-99" not in {c["code"] for c in client.get("/api/reg/controls").json()["controls"]}


# --------------------------------------------------------------------------- #
# 업무 프로세스 화면
# --------------------------------------------------------------------------- #
def test_process_view_counts_what_is_stuck_where(client):
    body = client.get("/api/reg/process").json()

    stages = {s["key"]: s for s in body["stages"]}
    assert list(stages) == list(analysis.SERVICE_STAGES), "단계 순서가 서비스 화면과 같아야 한다"
    # 서비스는 어느 한 단계에만 있다 — 합계가 전체와 같다
    total = sum(s["count"] for s in body["stages"])
    assert total == len(client.get("/api/reg/services").json()["services"])

    assert body["kpi"]["pending_changes"] >= 1
    assert 0.0 <= body["controls"]["rate"] <= 1.0
    assert body["controls"]["satisfied"] <= body["controls"]["total"]


def test_process_view_says_not_measured_instead_of_zero(client, tmp_path_factory, monkeypatch):
    """리드타임은 잰 것이 있을 때만 숫자를 낸다.

    표본이 없는데 0 을 내보내면 화면은 '즉시 승인' 이라고 읽는다. 그 숫자가
    감리에서 근거로 쓰이면 되돌릴 수 없다 — 없을 때는 없다고 말해야 한다.
    """
    from llmwiki.server import compliance as mod

    body = client.get("/api/reg/process").json()
    if body["kpi"]["lead_time_samples"] == 0:
        assert body["kpi"]["lead_time_days"] is None
        return

    # 표본이 있는 경우: 승인된 결재에서만 계산했는지 확인한다
    approved = [c for c in mod._store().read_changesets().values()
                if c.get("status") == cs.APPROVED and c.get("created_at") and c.get("reviewed_at")]
    assert body["kpi"]["lead_time_samples"] == len(approved)
    assert body["kpi"]["lead_time_days"] is not None


def test_process_queue_never_invents_a_deadline(client):
    """목업에는 '2h 남음' 같은 기한이 있지만 우리는 기한을 기록하지 않는다.

    큐 항목에 기한 필드가 생기면 화면이 그것을 정렬 기준으로 쓰게 되고,
    없는 것을 지어내는 자리가 열린다.
    """
    body = client.get("/api/reg/process").json()
    for row in body["queue"]:
        assert not ({"due", "due_at", "sla", "deadline", "remaining"} & set(row)), row


# --------------------------------------------------------------------------- #
# 프로젝트 결재 — 계획 승인 → 결과 승인, 등급이 승인권자를 정한다
# --------------------------------------------------------------------------- #
def _grade(client, uuid, key, label):
    """등급을 저장해 둔다. 결재는 저장된 등급에서 승인권자를 정하므로 전제 조건이다."""
    from llmwiki.server import compliance as mod
    store = mod._store()
    saved = store.read_json("risk_assessments.json", default={}) or {}
    saved[uuid] = {"result": {"final_grade": {"key": key, "label": label}}, "saved_by": "t"}
    store.write_json("risk_assessments.json", saved)


def test_grade_decides_who_approves(client):
    """회의에서 정해진 유일한 분기 — 고위험은 윤리위원회, 저·중위험은 거버넌스."""
    from llmwiki.compliance import approval as ap

    assert ap.approver_role("high") == ap.COMMITTEE
    assert ap.approver_role("unacceptable") == ap.COMMITTEE
    assert ap.approver_role("medium") == ap.GOVERNANCE
    assert ap.approver_role("low") == ap.GOVERNANCE
    # 고위험만 제3자 검증을 거친다
    assert ap.needs_verification("high") and not ap.needs_verification("medium")


def test_result_approval_needs_the_plan_first(client):
    _grade(client, "svc-call-summary", "medium", "중위험 서비스")
    early = client.post("/api/reg/approvals", json={
        "service_uuid": "svc-call-summary", "kind": "result", "by": "planner-a"})
    assert early.status_code == 400
    assert "계획 승인이 먼저" in early.json()["detail"]


def test_low_risk_runs_through_governance(client):
    _grade(client, "svc-call-summary", "medium", "중위험 서비스")
    made = client.post("/api/reg/approvals", json={
        "service_uuid": "svc-call-summary", "kind": "plan", "by": "planner-a"})
    assert made.status_code == 200, made.text
    row = made.json()
    assert row["approver_role"] == "governance"
    assert row["needs_verification"] is False

    # 윤리위원회는 이 건을 결정할 수 없다 — 등급이 정한 승인권자가 아니다
    wrong = client.post(f"/api/reg/approvals/{row['approval_id']}/decide",
                        json={"by": "chair", "role": "committee", "approve": True})
    assert wrong.status_code == 403

    # 상신자는 자기 건을 승인할 수 없다
    self_ok = client.post(f"/api/reg/approvals/{row['approval_id']}/decide",
                          json={"by": "planner-a", "role": "governance", "approve": True})
    assert self_ok.status_code == 403
    assert "상신자" in self_ok.json()["detail"]

    ok = client.post(f"/api/reg/approvals/{row['approval_id']}/decide",
                     json={"by": "gov-officer", "role": "governance", "approve": True})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "approved"


def test_high_risk_result_needs_third_party_verification(client):
    """고위험 경로가 검증 없이 뚫리지 않는다."""
    uuid = "svc-credit-scoring"
    _grade(client, uuid, "high", "고위험 서비스")

    plan = client.post("/api/reg/approvals", json={
        "service_uuid": uuid, "kind": "plan", "by": "planner-b"}).json()
    assert plan["approver_role"] == "committee"
    client.post(f"/api/reg/approvals/{plan['approval_id']}/decide",
                json={"by": "chair", "role": "committee", "approve": True})

    result = client.post("/api/reg/approvals", json={
        "service_uuid": uuid, "kind": "result", "by": "planner-b"}).json()
    assert result["needs_verification"] is True

    # 검증 없이 승인 → 막힌다
    early = client.post(f"/api/reg/approvals/{result['approval_id']}/decide",
                        json={"by": "chair", "role": "committee", "approve": True})
    assert early.status_code == 400
    assert "제3자 검증" in early.json()["detail"]

    # 검증기관이 결과를 등록한다 — 이것은 승인이 아니다
    ver = client.post(f"/api/reg/approvals/{result['approval_id']}/verify",
                      json={"by": "kisa", "result": "pass", "note": "샘플 검증"})
    assert ver.status_code == 200, ver.text
    assert ver.json()["status"] == "pending", "검증 등록이 승인이 되어서는 안 된다"

    ok = client.post(f"/api/reg/approvals/{result['approval_id']}/decide",
                     json={"by": "chair", "role": "committee", "approve": True})
    assert ok.status_code == 200, ok.text

    gate = client.get(f"/api/reg/approvals/gate/{uuid}").json()
    assert gate["deployable"] is True, "두 승인이 끝나면 IT 포털의 이행 버튼이 열린다"


def test_verifier_only_sees_what_it_must_verify(client):
    """사외 기관에 사내 서비스 목록 전체가 열리면 안 된다."""
    rows = client.get("/api/reg/approvals?role=verifier").json()["approvals"]
    assert all(r["needs_verification"] and r["status"] == "pending" for r in rows)


# --------------------------------------------------------------------------- #
# 데이터 폴더 분석 — 수치는 룰이 센다
# --------------------------------------------------------------------------- #
def _biased_csv() -> bytes:
    import csv as _csv, io as _io, random
    random.seed(11)
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["cust_id", "gender", "approve_yn", "memo"])
    for i in range(600):
        g = "M" if i % 2 == 0 else "F"
        ok = random.random() < (0.75 if g == "M" else 0.40)
        w.writerow([f"C{i}", g, "Y" if ok else "N", "" if i % 3 else "비고"])
    return buf.getvalue().encode("utf-8")


def test_data_analysis_measures_bias_without_calling_an_llm(client, monkeypatch):
    """같은 파일이면 같은 값이 나와야 한다 — 모델이 개입하면 그것을 보장할 수 없다."""
    from llmwiki.llm import base as llm_base

    def boom(*a, **k):  # pragma: no cover - 불리면 테스트가 실패한다
        raise AssertionError("데이터 분석은 LLM 을 부르지 않는다")

    monkeypatch.setattr(llm_base, "get_provider", boom)

    payload = _biased_csv()
    res = client.post(
        "/api/reg/data/analyze",
        files=[("files", ("loan.csv", payload, "text/csv"))],
        data={"paths": ["loan.csv"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    ds = body["datasets"][0]
    assert ds["rows"] == 600
    memo = next(c for c in ds["columns"] if c["name"] == "memo")
    assert memo["missing_ratio"] > 0.3

    bias = next(b for b in body["bias"] if b["protected"] == "gender")
    assert bias["di"] < 0.8 and bias["outside"] is True
    # 임계치의 출처를 함께 낸다 — RMF 규정값이 아니라 관행값이다
    assert bias["source"] and bias["scored"] is False

    # 32항목으로 이어지되 전부 후보다. 판정하지 않는다.
    items = {f["item_no"] for f in body["findings"]}
    assert {10, 11} <= items, "편향·공정성 항목이 후보로 올라와야 한다"
    assert all(f["confidence"] == "candidate" for f in body["findings"])


def test_data_analysis_is_deterministic(client):
    payload = _biased_csv()
    def run():
        return client.post("/api/reg/data/analyze",
                           files=[("files", ("loan.csv", payload, "text/csv"))],
                           data={"paths": ["loan.csv"]}).json()
    assert run()["bias"] == run()["bias"]


def test_uploaded_data_is_not_kept(client, tmp_path_factory):
    """올린 원본을 남기지 않는다 — 보존기간·파기 절차가 정해지기 전까지."""
    from llmwiki.server import compliance as mod

    before = set(p.name for p in mod._store().root.rglob("*"))
    client.post("/api/reg/data/analyze",
                files=[("files", ("loan.csv", _biased_csv(), "text/csv"))],
                data={"paths": ["loan.csv"]})
    after = set(p.name for p in mod._store().root.rglob("*"))
    assert after == before, "분석 후 저장소에 파일이 남으면 안 된다"
