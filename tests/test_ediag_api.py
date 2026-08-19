"""에너지 진단 위키 API — 화면이 규칙을 우회할 수 없다는 것을 고정한다.

API 로 게이트를 지나칠 수 있으면 나머지는 장식이다. 특히 셋:

* 서명 없이 확정되지 않는다
* 검산 미통과를 인지 없이 승인할 수 없다
* ACL 은 질의 인자로 넓힐 수 있어도 페이지 등급을 넘지 못한다
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmwiki.ediag import build as build_mod
from llmwiki.ediag.store import WikiStore, write_all

from test_ediag import _doc  # 같은 픽스처 문서를 쓴다 — 두 벌로 갈라지면 어긋난다

CONFIG = """
project:
  name: "에너지 진단 위키 API 테스트"
  source_roots: ["{root}/sample"]
compliance:
  dir: "{data}/compliance"
kb:
  dir: "{data}/knowledge"
  destination: ollama
wiki:
  dir: "{data}/wiki"
  pipeline_version: "v0.1.0-test"
  owner: "energy-team"
output:
  docs_dir: "{data}/docs"
  index_file: "{data}/docs/index.json"
llm:
  provider: template
"""


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("wikiapi")
    cfg_path = data / "config.yaml"
    cfg_path.write_text(
        CONFIG.format(root=Path(__file__).resolve().parents[1], data=data), encoding="utf-8")

    # 위키를 미리 채운다. 업로드 경로는 PDF 가 있어야 해서 여기서는 거부 경로만 본다.
    result = build_mod.build(_doc(), options=build_mod.BuildOptions(site_key="vitech"))
    store = WikiStore(data / "wiki")
    write_all(store, result.pages, actor="fixture")

    import llmwiki.server.app as app_module

    previous = os.environ.get("LLMWIKI_CONFIG")
    os.environ["LLMWIKI_CONFIG"] = str(cfg_path)
    importlib.reload(app_module)
    try:
        with TestClient(app_module.app) as c:
            c.wiki_root = data / "wiki"
            yield c
    finally:
        if previous is None:
            os.environ.pop("LLMWIKI_CONFIG", None)
        else:
            os.environ["LLMWIKI_CONFIG"] = previous
        importlib.reload(app_module)


# --------------------------------------------------------------------------- #
def test_health_reports_lint_and_units(client):
    r = client.get("/api/wiki/health")
    assert r.status_code == 200
    body = r.json()
    assert body["store"]["pages"] > 0
    assert body["lint"]["deployable"] is True
    assert body["units"]["version"]


def test_schema_exposes_closed_sets(client):
    body = client.get("/api/wiki/schema").json()
    assert [t["name"] for t in body["types"]]
    assert body["acl_levels"] == ["public", "internal", "confidential", "restricted"]
    assert "acl.inheritance" in body["blocking_codes"]


def test_pages_filter_by_acl(client):
    internal = client.get("/api/wiki/pages", params={"acl": "internal"}).json()
    assert all(p["acl"] in ("public", "internal") for p in internal["pages"])
    full = client.get("/api/wiki/pages", params={"acl": "confidential"}).json()
    assert len(full["pages"]) > len(internal["pages"])


def test_unknown_acl_is_rejected_not_silently_lowered(client):
    assert client.get("/api/wiki/pages", params={"acl": "top-secret"}).status_code == 400


def test_page_detail_carries_backlinks_and_findings(client):
    pages = client.get("/api/wiki/pages", params={"acl": "restricted"}).json()["pages"]
    measure = next(p for p in pages if p["type"] == "measure")
    body = client.get(f"/api/wiki/pages/{measure['stable_id']}",
                      params={"acl": "restricted"}).json()
    assert body["page"]["front_matter"]["stable_id"] == measure["stable_id"]
    assert "backlinks" in body and "findings" in body


def test_confidential_page_is_forbidden_not_hidden(client):
    """없는 것과 못 보는 것을 구분해 준다 — 구분하지 않으면 '지식이 없다' 고 결론 낸다."""
    pages = client.get("/api/wiki/pages", params={"acl": "confidential"}).json()["pages"]
    secret = next(p for p in pages if p["acl"] == "confidential")
    r = client.get(f"/api/wiki/pages/{secret['stable_id']}", params={"acl": "internal"})
    assert r.status_code == 403


def test_search_respects_acl(client):
    hits = client.get("/api/wiki/search",
                      params={"q": "에너지", "acl": "internal"}).json()["results"]
    assert hits
    assert all(h["acl"] in ("public", "internal") for h in hits)


def test_review_requires_signature(client):
    pages = client.get("/api/wiki/pages", params={"acl": "restricted"}).json()["pages"]
    target = pages[0]["stable_id"]
    r = client.post(f"/api/wiki/review/{target}", json={"decision": "approve", "actor": ""})
    assert r.status_code == 400


def test_review_requires_acknowledgement_for_unverified(client):
    pages = client.get("/api/wiki/pages", params={"acl": "restricted"}).json()["pages"]
    target = next(p for p in pages if not p["numeric_verified"])
    denied = client.post(f"/api/wiki/review/{target['stable_id']}",
                         json={"decision": "approve", "actor": "kim"})
    assert denied.status_code == 400

    ok = client.post(f"/api/wiki/review/{target['stable_id']}",
                     json={"decision": "approve", "actor": "kim",
                           "acknowledge_unverified": True, "note": "원문 오류로 판정"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "reviewed"

    journal = client.get("/api/wiki/review/journal").json()["journal"]
    assert journal[0]["actor"] == "kim"
    assert journal[0]["acknowledged_unverified"] is True


def test_queue_lists_pending_pages(client):
    body = client.get("/api/wiki/review/queue").json()
    assert body["queue"]
    assert body["queue"][0]["priority"] >= body["queue"][-1]["priority"]


def test_lint_endpoint_matches_health(client):
    lint = client.get("/api/wiki/lint").json()
    health = client.get("/api/wiki/health").json()
    assert lint["deployable"] == health["lint"]["deployable"]
    assert lint["pages"] == health["lint"]["pages"]


def test_calc_uses_the_same_functions_as_the_wiki(client):
    body = client.post("/api/wiki/calc",
                       json={"kw": 25.7, "hours": 7200, "load_pct": 80, "count": 18}).json()
    assert body["electricity"]["annual_kwh"] == pytest.approx(2_664_576)
    assert body["electricity"]["toe"] == pytest.approx(610.19, abs=0.01)


def test_calc_rejects_empty_input(client):
    assert client.post("/api/wiki/calc", json={}).status_code == 400


def test_routing_puts_acl_first(client):
    internal = client.get("/api/wiki/routing",
                          params={"task": "report_draft", "acl": "internal"}).json()
    secret = client.get("/api/wiki/routing",
                        params={"task": "report_draft", "acl": "confidential"}).json()
    assert internal["external_allowed"] is True
    assert secret["external_allowed"] is False


def test_upload_rejects_non_pdf(client):
    r = client.post("/api/wiki/preview",
                    files={"file": ("보고서.hwp", b"not a pdf", "application/octet-stream")},
                    data={"site": "vitech"})
    assert r.status_code == 400


def test_upload_rejects_empty_file(client):
    r = client.post("/api/wiki/ingest",
                    files={"file": ("보고서.pdf", b"", "application/pdf")},
                    data={"site": "vitech"})
    assert r.status_code == 400


def test_catalog_is_served_as_markdown(client):
    r = client.get("/api/wiki/index.md")
    assert r.status_code == 200
    assert "카탈로그" in r.text


# --------------------------------------------------------------------------- #
# 엔진 레이어 — 두 솔루션이 같은 엔진을 쓴다는 것을 한 곳에서 알린다
# --------------------------------------------------------------------------- #
def test_engines_report_all_four(client):
    body = client.get("/api/engines").json()
    assert [e["code"] for e in body["engines"]] == ["sllm", "grok", "rag", "aigov"]
    assert all(e["status"] in ("ok", "idle", "unavailable") for e in body["engines"])


def test_engine_without_data_is_idle_not_broken(client):
    """'자료가 없음' 과 '고장' 을 같은 빨간불로 보여 주면 멀쩡한 것을 고치려 든다."""
    rag = next(e for e in client.get("/api/engines").json()["engines"] if e["code"] == "rag")
    assert rag["status"] == "ok"           # 픽스처가 위키를 채워 두었다
    assert rag["detail"]["wiki_pages"] > 0


def test_engines_expose_the_routing_rule(client):
    """화면이 라우팅 규칙을 다시 구현하지 않도록 서버가 판정 결과를 준다."""
    examples = client.get("/api/engines").json()["routing"]["examples"]
    secret = [e for e in examples if e["acl"] == "confidential"]
    assert secret and all(e["external_allowed"] is False for e in secret)


def test_engines_are_cached_but_refreshable(client):
    first = client.get("/api/engines").json()
    assert client.get("/api/engines").json()["cached"] is True
    assert client.get("/api/engines", params={"refresh": True}).json()["cached"] is False
    assert first["engines"][0]["code"] == "sllm"


# --------------------------------------------------------------------------- #
# 재분석 반영 — 서술을 고치라고 부른 모델이 수치를 바꾸는 것이 가장 큰 위험이다
# --------------------------------------------------------------------------- #
def _a_measure(client) -> dict:
    pages = client.get("/api/wiki/pages", params={"acl": "restricted"}).json()["pages"]
    return next(p for p in pages if p["type"] == "measure")


def test_apply_requires_a_signature(client):
    page = _a_measure(client)
    r = client.post(f"/api/wiki/pages/{page['stable_id']}/apply",
                    json={"body": "# 제목\n\n## 요약\n고친 문장."})
    assert r.status_code == 400


def test_apply_blocks_numbers_the_model_invented(client):
    page = _a_measure(client)
    detail = client.get(f"/api/wiki/pages/{page['stable_id']}",
                        params={"acl": "restricted"}).json()["page"]
    tampered = detail["body"] + "\n\n회수기간은 2.8년으로 개선된다."
    r = client.post(f"/api/wiki/pages/{page['stable_id']}/apply",
                    json={"body": tampered, "actor": "kim"})
    assert r.status_code == 400
    assert "2.8" in r.json()["detail"]


def test_apply_blocks_a_rewrite_that_drops_sections(client):
    page = _a_measure(client)
    r = client.post(f"/api/wiki/pages/{page['stable_id']}/apply",
                    json={"body": "절이 하나도 없는 답변", "actor": "kim"})
    assert r.status_code == 400
    assert "절 구조" in r.json()["detail"]


def test_apply_bumps_version_and_sends_it_back_to_review(client):
    """반영한 내용은 다시 검토받아야 한다 — 예전 서명이 새 문장을 보증하지 않는다."""
    page = _a_measure(client)
    before = client.get(f"/api/wiki/pages/{page['stable_id']}",
                        params={"acl": "restricted"}).json()["page"]
    body = before["body"].replace("## 요약", "## 요약\n\n재분석으로 다듬은 문단.", 1)

    r = client.post(f"/api/wiki/pages/{page['stable_id']}/apply",
                    json={"body": body, "actor": "kim", "note": "재분석 반영"})
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "updated"

    after = client.get(f"/api/wiki/pages/{page['stable_id']}",
                       params={"acl": "restricted"}).json()["page"]
    assert after["version"] == before["version"] + 1
    assert after["status"] == "draft"
    assert "재분석으로 다듬은 문단" in after["body"]
