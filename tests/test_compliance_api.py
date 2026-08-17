"""규제 API — 읽기는 승인본만, 쓰기는 결재 경로만.

API 로 그래프에 직접 쓸 수 있으면 커밋 결재가 우회된다. 그 구멍이 없다는 것을
여기서 고정한다.
"""

from __future__ import annotations

import os

import pytest

import llmwiki.compliance.seed as seed_mod
from fastapi.testclient import TestClient

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
    assert client.get("/api/reg/schema").json()["ontology"] == "1.0.0"
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
    }


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
