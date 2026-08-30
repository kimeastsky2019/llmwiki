"""문서 지식베이스 API — 분석은 적재하지 않고, 적재는 게이트를 지나야 한다.

API 로 게이트를 우회할 수 있으면 나머지 규칙은 장식이다. 그 구멍이 없다는 것을
여기서 고정한다.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmwiki.kb import gate, taxonomy
from llmwiki.kb.ingest import AnalysisResult
from llmwiki.kb.store import Store

CONFIG = """
project:
  name: "지식베이스 API 테스트"
  source_roots: ["{root}/sample"]
compliance:
  dir: "{data}/compliance"
kb:
  dir: "{data}/knowledge"
  destination: ollama
output:
  docs_dir: "{data}/docs"
  index_file: "{data}/docs/index.json"
llm:
  provider: template
"""


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("kbapi")
    cfg_path = data / "config.yaml"
    cfg_path.write_text(
        CONFIG.format(root=Path(__file__).resolve().parents[1], data=data), encoding="utf-8"
    )
    # 서버 모듈은 임포트 시점에 설정을 읽는다. 이 테스트만 다른 설정을 보게 하고
    # 끝나면 되돌린다 — 안 그러면 뒤따르는 테스트가 이 설정을 물려받는다.
    import llmwiki.server.app as app_module

    previous = os.environ.get("LLMWIKI_CONFIG")
    os.environ["LLMWIKI_CONFIG"] = str(cfg_path)
    importlib.reload(app_module)
    try:
        with TestClient(app_module.app) as c:
            c.kb_root = data / "knowledge"          # 테스트가 저장소를 직접 들여다볼 때 쓴다
            yield c
    finally:
        if previous is None:
            os.environ.pop("LLMWIKI_CONFIG", None)
        else:
            os.environ["LLMWIKI_CONFIG"] = previous
        importlib.reload(app_module)


# --------------------------------------------------------------------------- #
# 상태 · 스키마 · 업종
# --------------------------------------------------------------------------- #
def test_health_reports_destination_and_parser(client):
    """pdfplumber 가 없거나 목적지가 국외면 화면이 먼저 알아야 한다."""
    h = client.get("/api/kb/health").json()
    assert h["status"] == "ok"
    assert h["channels"] == ["text", "table", "image", "excel"]
    assert h["destination"]["cross_border"] is False       # config 가 ollama 를 가리킨다
    assert {"ok", "reason", "hint", "formats"} <= set(h["parser_ready"])
    # 형식별 준비 상태가 따로 나와야 한다 — 이미지 OCR 만 빠진 상태는 정상적으로
    # 있을 수 있고, 그걸 전체 실패로 칠하면 멀쩡한 PDF 경로까지 막힌 것처럼 보인다.
    assert {"pdf", "sheet", "image"} <= set(h["parser_ready"]["formats"])


def test_sectors_are_the_closed_set(client):
    body = client.get("/api/kb/sectors").json()
    assert body["count"] == len(taxonomy.SECTOR_CODES)
    assert {s["code"] for s in body["sectors"]} == set(taxonomy.SECTOR_CODES)
    assert all(s["required_metrics"] and s["unit_basis"] for s in body["sectors"])


def test_sector_detail_and_unknown_sector(client):
    ok = client.get("/api/kb/sectors/waste").json()
    assert ok["partition"] == taxonomy.partition("waste")
    assert client.get("/api/kb/sectors/없는업종").status_code == 404


def test_sectors_follow_the_requested_language(client):
    en = client.get("/api/kb/sectors?lang=en").json()["sectors"]
    waste = next(s for s in en if s["code"] == "waste")
    assert waste["name"] == taxonomy.get("waste").name_en
    assert waste["name_ko"] == taxonomy.get("waste").name


def test_schema_declares_the_ontology(client):
    s = client.get("/api/kb/schema").json()
    assert s["ontology"] == "0.1.0"
    assert "Quantity" in s["nodes"]
    assert s["nodes"]["Quantity"]["requires_span"] is True


# --------------------------------------------------------------------------- #
# 게이트
# --------------------------------------------------------------------------- #
def test_gate_review_is_rule_based_and_deterministic(client):
    payload = {"text": "담당자: 허만수 (063)635-8991", "destination_provider": "claude"}
    a = client.post("/api/kb/gate/review", json=payload).json()
    b = client.post("/api/kb/gate/review", json=payload).json()
    assert a == b
    assert a["verdict"] == "BLOCKED"
    assert any(f["rule"] == "privacy.cross_border" for f in a["findings"])


def test_gate_review_follows_the_destination(client):
    """같은 문서라도 사내 모델로 돌리면 국외 이전이 아니다."""
    payload = {"text": "담당자: 허만수 (063)635-8991", "destination_provider": "ollama"}
    r = client.post("/api/kb/gate/review", json=payload).json()
    assert r["upload_allowed"]
    assert r["destination"]["cross_border"] is False


def test_gate_mask_verifies_itself(client):
    r = client.post("/api/kb/gate/mask", json={"text": "문의 (063)635-8991"}).json()
    assert r["clean"] and r["residual_count"] == 0
    assert "[전화번호]" in r["masked_text"]


def test_gate_endpoints_reject_empty_input(client):
    assert client.post("/api/kb/gate/review", json={"text": "  "}).status_code == 400
    assert client.post("/api/kb/gate/mask", json={}).status_code == 400


# --------------------------------------------------------------------------- #
# 업로드 검증
# --------------------------------------------------------------------------- #
def test_supported_formats_are_a_closed_set(client):
    """PDF·엑셀·이미지는 받고 그 밖은 막는다. 목록의 원본은 `kb/sources.py` 하나다."""
    r = client.post("/api/kb/analyze",
                    files={"file": ("보고서.docx", b"x", "application/msword")})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert ".docx" in detail and ".xlsx" in detail

    # 확장자는 통과하고 내용이 깨진 경우는 다른 오류다 — 형식 거부(400)와 구분된다.
    broken = client.post("/api/kb/analyze",
                         files={"file": ("계측.xlsx", b"not a workbook",
                                         "application/vnd.ms-excel")})
    assert broken.status_code != 400 or ".xlsx" not in broken.json().get("detail", "")


def test_empty_file_is_rejected(client):
    r = client.post("/api/kb/analyze", files={"file": ("x.pdf", b"", "application/pdf")})
    assert r.status_code == 400


def test_unknown_sector_is_rejected_before_parsing(client):
    r = client.post(
        "/api/kb/analyze",
        files={"file": ("x.pdf", b"%PDF-1.4 ...", "application/pdf")},
        data={"sector": "없는업종"},
    )
    assert r.status_code == 400


# --------------------------------------------------------------------------- #
# 그래프 도구
# --------------------------------------------------------------------------- #
GRAPH = {
    "ontology": "0.1.0",
    "nodes": [
        {"id": "dgn:t1", "type": "Diagnosis", "derivation": "documented",
         "name": "t.pdf", "doc_hash": "abc", "pages": 1, "sector": "waste"},
        {"id": "span:t1/p1/tbl0", "type": "EvidenceSpan", "derivation": "documented", "page": 1},
    ],
    "edges": [{"type": "evidencedBy", "source": "dgn:t1", "target": "span:t1/p1/tbl0",
               "derivation": "documented"}],
}


def test_ttl_export(client):
    r = client.post("/api/kb/graph/ttl", json=GRAPH).json()
    assert r["ttl"].startswith("@prefix ed:")
    assert r["lines"] > 0
    assert client.post("/api/kb/graph/ttl", json={"x": 1}).status_code == 400


def test_graph_validate_catches_a_broken_graph(client):
    assert client.post("/api/kb/graph/validate", json=GRAPH).json()["ok"] is True
    broken = {**GRAPH, "nodes": [{**GRAPH["nodes"][0], "derivation": "static"}]}
    out = client.post("/api/kb/graph/validate", json=broken).json()
    assert out["ok"] is False and out["errors"] >= 1


# --------------------------------------------------------------------------- #
# 적재 — 우회로가 없다
# --------------------------------------------------------------------------- #
def _result(**kw) -> AnalysisResult:
    res = AnalysisResult(
        filename="보고서.pdf", doc_hash="feedface", sector="waste",
        sector_name=taxonomy.get("waste").name, needs_review=False,
        partition=taxonomy.partition("waste"), upload_allowed=True,
        gate={"pii_detected": 1, "verdict": "CONDITIONAL"}, graph_stats={"nodes": 2},
    )
    res.chunks = [{"channel": "text", "content": "담당자: 허만수 (063)635-8991 송풍기 측정",
                   "page": 1, "anchor": "p1/t0"}]
    for k, v in kw.items():
        setattr(res, k, v)
    return res


def test_documents_and_search_are_empty_before_ingest(client):
    body = client.get("/api/kb/documents").json()
    assert body["documents"] == [] and body["stats"]["records"] == 0
    assert client.get("/api/kb/search?q=송풍기").json()["results"] == []


def test_search_rejects_an_unknown_channel(client):
    assert client.get("/api/kb/search?q=x&channel=pdf").status_code == 400


def test_missing_document_is_404(client):
    assert client.get("/api/kb/documents/nope").status_code == 404
    assert client.get("/api/kb/documents/nope/graph").status_code == 404
    assert client.get("/api/kb/documents/nope/tables.xlsx").status_code == 404


def test_ingested_document_is_masked_and_searchable(client):
    """적재는 API 뒤의 저장소가 한다 — 같은 게이트를 통과해야 검색에 나온다."""
    store = Store(client.kb_root)
    record = store.ingest(_result())
    assert record["stored"] == 1

    body = client.get("/api/kb/documents").json()
    assert [d["doc_hash"] for d in body["documents"]] == ["feedface"]
    assert body["stats"]["sectors"] == {"waste": 1}

    hits = client.get("/api/kb/search?q=송풍기&sector=waste").json()["results"]
    assert hits and hits[0]["doc_hash"] == "feedface"
    assert not gate.detect_pii(hits[0]["snippet"]), "검색 결과에 개인정보가 새어 나왔다"

    detail = client.get("/api/kb/documents/feedface").json()
    assert detail["masked"] is True and detail["analysis"]["sector"] == "waste"

    # 업종 필터가 실제로 걸린다 — 다른 업종으로 물으면 나오지 않는다
    assert client.get("/api/kb/search?q=송풍기&sector=building").json()["results"] == []


def test_store_refuses_a_blocked_document_through_the_same_path(client):
    store = Store(client.kb_root)
    before = len(store.documents())
    out = store.ingest(_result(doc_hash="blocked1", upload_allowed=False))
    assert out["stored"] == 0
    assert len(store.documents()) == before
    assert client.get("/api/kb/documents/blocked1").status_code == 404


# --------------------------------------------------------------------------- #
# 목적지 선택 — 화면이 고른 공급자가 판정에 그대로 들어간다
# --------------------------------------------------------------------------- #
def test_health_lists_selectable_destinations(client):
    """화면이 목록을 따로 들고 있으면 공급자가 늘었을 때 한쪽만 갱신된다."""
    h = client.get("/api/kb/health").json()
    assert [d["provider"] for d in h["destinations"]] == list(gate.SELECTABLE_PROVIDERS)
    # 기본값이 무엇인지도 함께 말한다 — 아무것도 고르지 않았을 때의 판정 기준이다
    assert h["destination"]["provider"] == "ollama"      # config 가 가리키는 값
    assert h["destination"]["cross_border"] is False


def test_unknown_destination_provider_is_rejected(client):
    """모르는 값을 조용히 국외로 판정하면 어느 쪽을 고른 결과인지 알 수 없다.
    화면이 보낸 값은 드롭다운의 닫힌 집합 밖일 이유가 없으므로 거절한다."""
    r = client.post(
        "/api/kb/analyze",
        files={"file": ("x.pdf", b"%PDF-1.4 ...", "application/pdf")},
        data={"destination_provider": "openai"},
    )
    assert r.status_code == 400
    assert "openai" in r.json()["detail"]


def test_destination_choice_changes_the_gate_verdict(client):
    """같은 문서라도 어디로 보내느냐에 따라 국외 이전 조항이 걸리고 안 걸린다."""
    text = "담당자 홍길동 010-1234-5678 이 확인한 루츠블로워 22kW"

    def rules(provider: str | None) -> set[str]:
        body = {"text": text}
        if provider:
            body["destination_provider"] = provider
        report = client.post("/api/kb/gate/review", json=body).json()
        return {f["rule"] for f in report["findings"]}

    assert "privacy.cross_border" in rules("grok")
    assert "privacy.cross_border" not in rules("ollama")
    # 고르지 않으면 서버 설정(ollama)을 따른다
    assert "privacy.cross_border" not in rules(None)


def test_ledger_records_what_the_judgement_was_based_on(client):
    """판정만 남기면 재현되지 않는다 — 목적지가 바뀌면 같은 문서도 결과가 달라진다."""
    store = Store(client.kb_root)
    dest = {"provider": "grok", "name": "xAI (미국)", "cross_border": True, "note": ""}
    record = store.ingest(_result(doc_hash="destrec1"), destination=dest)
    assert record["stored"] == 1
    assert record["destination"] == dest

    # 목적지를 주지 않으면 게이트 판정에 쓰인 값으로 되돌아간다 — 조용히 비지 않는다
    judged = {"name": "사내 GPU (Ollama)", "cross_border": False}
    plain = store.ingest(
        _result(doc_hash="destrec2",
                gate={"pii_detected": 1, "verdict": "CONDITIONAL", "destination": judged})
    )
    assert plain["destination"] == judged
