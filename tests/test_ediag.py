"""에너지 진단 위키 — 설계 결정을 지키는 테스트.

성능 테스트가 아니다. 누가 나중에 편의를 위해 다음 중 하나를 하면 여기서 걸려야 한다.

* 수치를 코드가 아니라 서술로 만들기 (P2)
* front-matter 없이 페이지 만들기 (P3)
* 낮은 등급 페이지가 높은 등급 페이지를 참조하게 두기 (P5)
* 검산에 실패한 페이지를 조용히 승인하기
* 계수를 `units.yaml` 이 아니라 코드에 적기

`llmwiki/kb/` 테스트가 게이트 우회와 좌표 ID 를 막는 것과 같은 역할이다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from llmwiki.ediag import (
    build as build_mod,
    calc,
    contract,
    extract,
    lint as lint_mod,
    page as page_mod,
    retrieval,
    review,
    route,
    terms,
    units as units_mod,
)
from llmwiki.ediag.store import WikiStore, write_all
from llmwiki.kb import parse


# --------------------------------------------------------------------------- #
# 문서 픽스처 — 실제 진단 보고서(비이테크 2026-04)의 표 구조를 그대로 옮긴 것.
# 숫자도 원문 값이라, 검산이 통과/실패하는 지점이 실제와 같다.
# --------------------------------------------------------------------------- #
def _table(page: int, idx: int, header: list[str], rows: list[list[str]],
           caption: str = "") -> parse.TableBlock:
    return parse.TableBlock(page=page, idx=idx, header=header, rows=rows, caption=caption)


def _doc() -> parse.ParsedDocument:
    doc = parse.ParsedDocument(filename="진단보고서.pdf", doc_hash="0ff12005ca241d21",
                               n_pages=32)
    doc.tables = [
        _table(4, 0, ["업 체 명", "농업회사법인 주식회사 비이테크", "", ""], [
            ["대 표 자", "허 인 구", "사업자등록번호", "623-86-00165"],
            ["소 재 지", "전라북도 남원시 대강면 섬진로 1200-27", "", ""],
            ["전 화 번 호", "(063) 635-8991", "FAX 번호", "(063) 635-8993"],
            ["설 립 년 도", "2015년 9월", "연평균 가동시간", "약 3,000(h/y)"],
            ["담 당 자", "허 만 수", "E-mail", "vitech1200@naver.com"],
        ]),
        _table(7, 1, ["위치", "수량", "용량 (kW)", "토출유량 (㎥/min)", "사용압력 (mmAq)",
                      "제작년도", "제작사", "모델"], [
            ["2차 숙성실", "18대", "22", "8.0", "-4500", "2002년", "한국유체기계", "SP 125V"],
            ["건조실", "10대", "22", "8.0", "-4500", "2002년", "한국유체기계", "SP 125V"],
        ], caption="루츠블로워 설치현황"),
        _table(8, 0, ["구 분", "평균 단가 (부가세 별도)", "", "적용 기준"], [
            ["LPG [탱크로리 공급]", "1,897(원/㎏)", "", "2025년 10월 구입단가 적용"],
            ["전력 [산업용(을)]", "195(원/kWh)", "", "2025년 12월 한전고지서적용"],
        ]),
        _table(11, 0, ["기번", "측정일자 (시간)", "측정 시간", "측정전력(kW)", "",
                       "부하율 (%)", "비고"], [
            ["#1", "6.17(13:14~13:20)", "7분", "25.3~29.9", "25.7", "117", ""],
        ]),
        _table(12, 0, ["위치", "수량", "정격전력 (kW)", "운전전력 (kW)", "연간가동 시간(h/y)",
                       "안전률 (%)", "연간 전력량 (kWh/y)", "비고"], [
            ["2차 숙성실", "18대", "22", "25.7", "7,200", "80", "2,664,576", ""],
            ["건조실", "10대", "22", "23.0", "7,200", "80", "1,324,800", ""],
            ["계", "28대", "-", "(24.7)", "7,200", "80", "3,989,376", ""],
        ]),
        _table(31, 0, ["구분", "항목", "단위", "개선전(a)", "개선후(b)", "증감(b-a)",
                       "증감률(%)"], [
            ["전기", "전력량", "kWh", "4,241,376", "372,525", "-3,868,851", ""],
            ["", "에너지량", "toe", "971.27", "85.29", "-885.98", ""],
            # ↓ 원문의 실제 오류. 169.15 - 1,926.01 = -1,756.86 이어야 한다.
            ["", "온실가스량", "tCO eq 2", "1,926.01", "169.15", "-2,095.16", ""],
            ["LPG", "에너지량", "toe", "90.72", "254.02", "163.3", ""],
            ["계", "금액", "천원", "970,481", "474,199", "-496,282", "- 51.1"],
            ["", "에너지량", "toe", "1,061.9", "339.31", "-722.59", "- 68.0"],
        ]),
        _table(32, 0, ["", "품 명", "구 분", "수량", "단위", "금 액(천원)"], [
            ["1", "재료비", "", "1", "식", "1,664,246"],
            ["합 계", "", "", "", "", "2,269,000"],
        ]),
    ]
    doc.text_blocks = [
        parse.TextBlock(page=1, idx=0, text="에너지진단 보고서\n2026년 4월"),
        parse.TextBlock(page=5, idx=0,
                        text="- 처리시설 : 음식물류 폐기물쓰레기 1일 처리용량 48(ton)"),
        parse.TextBlock(page=12, idx=0, text=(
            "(주1) 연간가동시간 : 유지보수 및 안전점검 등을 위하여 연간 300일 가동기간 적용\n"
            "= 24(h/d) × 300(d/y) = 7,200(h/y)")),
        parse.TextBlock(page=13, idx=0, text=(
            "- 연간 환산에너지사용량\n"
            "= 3,989.37(MWh) × 0.229(toe/MWh) = 913.57(toe)")),
        # ↓ 원문의 실제 오류. 10 × 300 = 3,000 인데 3,600 으로 적혀 있다.
        parse.TextBlock(page=22, idx=0, text=(
            "1) 전력량 소비기준(교반기)\n"
            "195(원/kWh) 90(kW) 10(h) × 300(d) = 3,600(y) 60(%)\n"
            "2. 회전식 디스크 건조기 도입")),
        parse.TextBlock(page=23, idx=0, text="3. 노통연관 (폐열)보일러(3t) 도입"),
        parse.TextBlock(page=13, idx=1, text=(
            "1) 문제점\n- 루츠블로워 노후화에 따른 소음진동 증가와 전력소비량이 많다.\n"
            "2) 개선방안\n- 시스템 전체의 설비 교체가 필요하다고 판단된다.")),
        parse.TextBlock(page=32, idx=0, text=(
            "라. 투자비 회수기간 : 투자비 ÷ 연간 절감금액\n"
            "= 2,269,000(천원) ÷ 496,282(천원/년)\n= 4.6 (년)")),
    ]
    return doc


@pytest.fixture(scope="module")
def doc() -> parse.ParsedDocument:
    return _doc()


@pytest.fixture(scope="module")
def extraction(doc):
    return extract.extract(doc)


@pytest.fixture()
def wiki(tmp_path, doc):
    result = build_mod.build(doc, options=build_mod.BuildOptions(site_key="vitech"))
    store = WikiStore(tmp_path / "wiki")
    write_all(store, result.pages, actor="tester", note="테스트 생성")
    return store, result


# --------------------------------------------------------------------------- #
# 단위 SSOT — 계수는 코드에 없다
# --------------------------------------------------------------------------- #
def test_factors_live_in_yaml_not_in_code():
    """계산 코드에 계수 상수가 박히면 개정 때 무엇이 옛 값으로 돌았는지 알 수 없다.

    주석·독스트링은 계수를 설명하려고 값을 적는다. 검사 대상은 **실행되는 수**뿐이라
    소스 문자열이 아니라 AST 의 숫자 리터럴을 본다.
    """
    tree = ast.parse(Path(calc.__file__).read_text(encoding="utf-8"))
    literals = {
        float(n.value) for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float))
        and not isinstance(n.value, bool)
    }
    table = units_mod.load()
    for factor in table.factors:
        assert factor.value not in literals, f"계수 {factor.code} 가 calc.py 에 박혀 있다"


def test_unknown_factor_raises():
    with pytest.raises(KeyError):
        units_mod.load().factor("존재하지.않는계수")


def test_factor_expiry_is_tracked():
    table = units_mod.load()
    assert all(f.valid_until for f in table.factors), "유효기간 없는 계수는 개정을 놓친다"


# --------------------------------------------------------------------------- #
# 계산 — 원문 값과 자리까지 맞아야 한다
# --------------------------------------------------------------------------- #
def test_annual_electricity_matches_report():
    kwh = calc.annual_kwh(25.7, 7200, 0.8, 18) + calc.annual_kwh(23.0, 7200, 0.8, 10)
    assert kwh == pytest.approx(3_989_376)
    assert calc.toe_from_kwh(kwh) == pytest.approx(913.57, abs=0.01)
    assert calc.tco2eq_from_kwh(kwh) == pytest.approx(1811.58, abs=0.01)
    assert calc.elec_cost_kwon(kwh) == pytest.approx(777_928, abs=1)


def test_lpg_uses_per_ton_factor_not_per_toe():
    """원문 라벨(`tCO2eq/toe`)대로 곱하면 배출량이 20% 부풀려진다."""
    kg = calc.annual_fuel_kg(36, 10, 300, 0.7)
    assert kg == pytest.approx(75_600)
    assert calc.tco2eq_from_lpg_kg(kg) == pytest.approx(220.60, abs=0.01)
    wrong = calc.toe_from_lpg_kg(kg) * units_mod.load().value("lpg.tco2eq_per_ton")
    assert wrong > calc.tco2eq_from_lpg_kg(kg)


def test_boiler_fuel_rate_matches_report():
    assert calc.boiler_fuel_rate_kg_h(3.0, 0.6, 0.89) == pytest.approx(117.6, abs=0.2)


def test_payback_never_returns_zero_when_no_saving():
    """'회수기간 0년' 은 이 도메인에서 가장 위험한 표시다."""
    assert calc.payback_years(2_269_000, 0) == float("inf")
    assert calc.payback_years(2_269_000, -10) == float("inf")


def test_check_accepts_report_rounding_but_not_real_errors():
    ok = calc.check("회수기간", 4.5719, 4.6, "년")
    assert ok.ok, "원문이 적은 자릿수까지 맞으면 통과여야 한다"
    bad = calc.check("증감", 1756.86, 2095.16, "tCO2eq")
    assert not bad.ok


def test_energy_intensity_rejects_zero_denominator():
    with pytest.raises(ValueError):
        calc.energy_intensity(1000.0, 0)


# --------------------------------------------------------------------------- #
# 추출 — 원문의 오류를 찾아낸다
# --------------------------------------------------------------------------- #
def test_extraction_finds_the_two_real_errors(extraction):
    labels = [c.label for c in extraction.failed]
    assert any("온실가스" in l for l in labels), "집계표 증감 오류를 놓쳤다"
    assert any("계산식" in l for l in labels), "본문 계산식 오류를 놓쳤다"


def test_extraction_does_not_flag_correct_rows(extraction):
    passed = [c for c in extraction.checks if c.ok]
    assert any("연간 전력량" in c.label for c in passed)
    assert len(passed) > len(extraction.failed)


def test_pii_fields_are_dropped_not_copied(extraction):
    assert extraction.pii_dropped >= 3
    joined = " ".join(f"{k}{v}" for k, v in extraction.facility.items())
    for leak in ("허 만 수", "vitech1200@naver.com", "623-86-00165"):
        assert leak not in joined


def test_equipment_groups_by_spec_not_by_location(extraction):
    blowers = [f for f in extraction.equipment if f.fields["term"] == "roots-blower"]
    assert len(blowers) == 1, "같은 설비가 위치별로 쪼개지면 설비-개선안 연결이 깨진다"
    assert blowers[0].fields["total_count"] == 28
    assert {i["location"] for i in blowers[0].fields["installations"]} == {"2차 숙성실", "건조실"}


def test_location_words_never_become_equipment_names():
    assert terms.is_location("2차 숙성실")
    ascii_term, needs_naming = terms.ascii_term("듣도보도못한설비")
    assert needs_naming, "모르는 명칭은 번역을 지어내지 않고 사람에게 넘긴다"


# --------------------------------------------------------------------------- #
# 데이터 컨트랙트
# --------------------------------------------------------------------------- #
def test_every_generated_page_satisfies_the_contract(wiki):
    _store, result = wiki
    for p in result.pages:
        assert p.validate().ok, f"{p.stable_id}: {[i.message for i in p.validate().errors]}"


def test_contract_rejects_missing_fields():
    assert not contract.validate({"stable_id": "ecm-x", "type": "measure"}).ok


def test_contract_rejects_prefix_type_mismatch():
    fm = contract.new_front_matter(
        stable_id="ecm-x", page_type="equipment", body="b",
        source_span=[{"doc": "a.pdf", "pages": [1]}])
    codes = [i.code for i in contract.validate(fm, "b").issues]
    assert "schema.prefix_mismatch" in codes


def test_measurement_basis_is_a_closed_set():
    fm = contract.new_front_matter(
        stable_id="mtr-x", page_type="metric", body="b",
        source_span=[{"doc": "a.pdf", "pages": [1]}], measurement_basis="대충")
    assert "schema.bad_basis" in [i.code for i in contract.validate(fm, "b").issues]


def test_acl_reference_rule():
    assert contract.acl_allows_reference("confidential", "public")
    assert not contract.acl_allows_reference("public", "confidential")


# --------------------------------------------------------------------------- #
# 저장소
# --------------------------------------------------------------------------- #
def test_rewrite_without_change_does_not_bump_version(wiki, doc):
    store, _ = wiki
    again = build_mod.build(doc, options=build_mod.BuildOptions(site_key="vitech"))
    records = [store.write(p, actor="tester") for p in again.pages]
    assert all(r["action"] == "unchanged" for r in records)
    assert all(r["version"] == 1 for r in records)


def test_content_change_invalidates_review(wiki):
    store, _ = wiki
    target = store.pages(page_type="measure")[0]
    review.decide(store, target.stable_id, "approve", actor="kim",
                  acknowledge_unverified=True)
    assert store.read(target.stable_id).status == "reviewed"

    edited = store.read(target.stable_id)
    edited.body += "\n\n## 추가\n검토 후 덧붙인 문단."
    record = store.write(edited, actor="kim")
    assert record["action"] == "updated"
    assert store.read(target.stable_id).status == "draft", "본문이 바뀌면 검토는 무효다"
    assert store.read(target.stable_id).version == 2


def test_log_is_append_only(wiki):
    store, _ = wiki
    before = len(store.log(limit=1000))
    store.set_status(store.pages()[0].stable_id, "deprecated", actor="kim", note="테스트")
    assert len(store.log(limit=1000)) == before + 1


# --------------------------------------------------------------------------- #
# Lint
# --------------------------------------------------------------------------- #
def test_generated_wiki_is_lint_clean(wiki):
    store, _ = wiki
    res = lint_mod.run(store)
    assert res.clean, [f.to_dict() for f in res.findings if f.severity in ("blocker", "error")]
    assert res.deployable


def test_broken_link_is_an_error(wiki):
    store, _ = wiki
    p = store.pages(page_type="concept")[0]
    p.body += "\n\n[[ecm-존재하지-않는-카드]]"
    store.write(p, actor="tester")
    codes = [f.code for f in lint_mod.run(store).findings]
    assert "link.broken" in codes


def test_acl_inheritance_violation_blocks_deployment(wiki):
    """낮은 등급이 높은 등급을 참조하면 배포가 막혀야 한다 (P5)."""
    store, _ = wiki
    card = store.pages(page_type="measure")[0]
    dgn = store.pages(page_type="diagnosis")[0]
    card.body += f"\n\n## 적용 사례\n- [[{dgn.stable_id}]]"
    store.write(card, actor="tester")
    res = lint_mod.run(store)
    assert not res.deployable
    finding = next(f for f in res.findings if f.code == "acl.inheritance")
    assert finding.severity == "blocker"


def test_duplicate_stable_id_fails_immediately(wiki):
    store, _ = wiki
    p = store.pages(page_type="metric")[0]
    (store.root / "concepts" / f"{p.stable_id}.md").write_text(p.dumps(), encoding="utf-8")
    res = lint_mod.run(store)
    assert any(f.code == "id.duplicate" and f.severity == "blocker" for f in res.findings)


def test_unit_label_mismatch_is_reported(wiki):
    store, _ = wiki
    p = store.pages(page_type="concept")[0]
    p.body += "\n\n온실가스 배출량 = 211,680(kg) × 2.918(tCO2eq/toe)"
    store.write(p, actor="tester")
    codes = [f.code for f in lint_mod.run(store).findings]
    assert "unit.label_mismatch" in codes


# --------------------------------------------------------------------------- #
# 검증 워크플로
# --------------------------------------------------------------------------- #
def test_unverified_page_needs_explicit_acknowledgement(wiki):
    store, _ = wiki
    target = next(p for p in store.pages() if not p.numeric_verified)
    with pytest.raises(review.ReviewError):
        review.decide(store, target.stable_id, "approve", actor="kim")
    rec = review.decide(store, target.stable_id, "approve", actor="kim",
                        acknowledge_unverified=True, note="원문 오류로 판정")
    assert rec["status"] == "reviewed"
    assert rec["acknowledged_unverified"]


def test_blocking_finding_cannot_be_waved_through(wiki):
    store, _ = wiki
    card = store.pages(page_type="measure")[0]
    dgn = store.pages(page_type="diagnosis")[0]
    card.body += f"\n\n[[{dgn.stable_id}]]"
    store.write(card, actor="tester")
    with pytest.raises(review.ReviewError):
        review.decide(store, card.stable_id, "approve", actor="kim",
                      acknowledge_unverified=True)


def test_signature_is_required(wiki):
    store, _ = wiki
    with pytest.raises(review.ReviewError):
        review.decide(store, store.pages()[0].stable_id, "approve", actor="  ")


def test_review_journal_is_append_only(wiki):
    store, _ = wiki
    page_id = store.pages(page_type="regulation")[0].stable_id
    review.decide(store, page_id, "approve", actor="kim")
    review.decide(store, page_id, "deprecate", actor="lee", note="계수 개정")
    rows = review.journal(store, stable_id=page_id)
    assert len(rows) == 2, "결정은 덮어쓰이지 않고 쌓인다"
    assert {r["decision"] for r in rows} == {"approve", "deprecate"}


def test_signed_off_page_leaves_the_queue(wiki):
    """치울 수 없는 큐는 아무도 보지 않는다. 서명이 끝나면 빠져야 한다."""
    store, _ = wiki
    target = next(p for p in store.pages() if not p.numeric_verified)
    review.decide(store, target.stable_id, "approve", actor="kim",
                  acknowledge_unverified=True)
    assert target.stable_id not in [i.stable_id for i in review.queue(store)]

    edited = store.read(target.stable_id)
    edited.body += "\n\n검토 후 덧붙인 문단."
    store.write(edited, actor="kim")
    assert target.stable_id in [i.stable_id for i in review.queue(store)], (
        "본문이 바뀌면 다시 검토 대상이 되어야 한다")


def test_queue_orders_by_what_breaks_if_ignored(wiki):
    store, _ = wiki
    items = review.queue(store)
    assert items, "초안이 있으면 큐가 비어 있을 수 없다"
    assert items == sorted(items, key=lambda i: (-i.priority, i.stable_id))


# --------------------------------------------------------------------------- #
# 검색
# --------------------------------------------------------------------------- #
def test_acl_filter_is_applied_by_code(wiki):
    store, _ = wiki
    index = retrieval.Index(store.pages())
    hits = index.search("에너지", acl_max="internal", limit=50)
    assert hits
    assert all(h.acl in ("public", "internal") for h in hits)


def test_hybrid_finds_spacing_variants(wiki):
    """`루츠블로워` 와 `루츠 블로워` 가 같은 보고서에 섞여 있다."""
    store, _ = wiki
    index = retrieval.Index(store.pages())
    assert index.search("루츠 블로워", acl_max="confidential")
    assert index.search("루츠블로워", acl_max="confidential")


def test_rrf_fuses_two_channels(wiki):
    store, _ = wiki
    index = retrieval.Index(store.pages())
    hits = index.search("루츠블로워 전력", acl_max="confidential", limit=5)
    assert any(len(h.ranks) == 2 for h in hits), "두 채널이 모두 기여해야 융합이다"


# --------------------------------------------------------------------------- #
# 라우팅
# --------------------------------------------------------------------------- #
def test_acl_beats_task_difficulty():
    """보안이 성능보다 먼저다 — 순서를 뒤집으면 confidential 이 외부로 나간다."""
    hard = route.decide("report_draft", "internal")
    assert hard.external_allowed
    secret = route.decide("report_draft", "confidential")
    assert not secret.external_allowed
    assert secret.provider in route.INTERNAL_PROVIDERS


def test_unknown_task_defaults_to_internal():
    d = route.decide("듣도보도못한작업", "public")
    assert not d.external_allowed


# --------------------------------------------------------------------------- #
# 페이지 직렬화
# --------------------------------------------------------------------------- #
def test_round_trip_keeps_hash_stable(wiki):
    _store, result = wiki
    for p in result.pages:
        again = page_mod.loads(p.dumps())
        assert again.front_matter["content_hash"] == p.front_matter["content_hash"]
        assert again.body == p.body


def test_body_links_count_as_relations():
    p = page_mod.build(stable_id="cpt-x", page_type="concept", title="t",
                       body="본문에서만 링크한다 [[ecm-y]]",
                       source_span=[{"doc": "a.pdf", "pages": [1]}])
    assert "ecm-y" in p.related


def test_index_is_regenerated_not_edited(wiki):
    store, _ = wiki
    store.index_path.write_text("사람이 직접 고친 카탈로그", encoding="utf-8")
    store.rebuild_index()
    assert "사람이 직접 고친" not in store.index_path.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 서술 초안 제안 — LLM 은 말만 쓰고 수는 못 쓴다
# --------------------------------------------------------------------------- #
class _StubProvider:
    """네트워크를 타지 않는 공급자. 무엇을 물었는지와 무엇을 답할지를 시험이 정한다."""

    name = "stub"
    last: dict[str, str] = {}

    def __init__(self, answer: str) -> None:
        self.answer = answer

    def complete(self, system: str, prompt: str) -> str:
        _StubProvider.last = {"system": system, "prompt": prompt}
        return self.answer


def _cfg(provider: str = "grok"):
    from llmwiki.config import Config

    return Config(raw={"llm": {"provider": provider, "grok": {}, "ollama": {}}},
                  root=Path("."))


def _patch_provider(monkeypatch, answer: str):
    from llmwiki.ediag import assist as assist_mod

    monkeypatch.setattr(assist_mod, "get_provider",
                        lambda name, options: _StubProvider(answer))


def test_confidential_page_never_goes_to_an_external_model(wiki, monkeypatch):
    """P5. 등급이 먼저고 난이도는 그다음이다."""
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "초안")
    page = store.pages(page_type="diagnosis")[0]
    assert page.acl == "confidential"
    s = assist_mod.suggest(page, cfg=_cfg("grok"), task="concept", provider="external")
    assert s.provider in route.INTERNAL_PROVIDERS
    assert s.external is False


def test_default_route_is_internal_not_external(wiki, monkeypatch):
    """고르지 않았을 때의 기본이 사외 전송이면 언젠가 모르고 내보낸다."""
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "초안")
    card = store.pages(page_type="measure")[0]
    s = assist_mod.suggest(card, cfg=_cfg("grok"), task="concept")
    assert s.provider == "ollama" and s.external is False


def test_external_runs_only_when_chosen(wiki, monkeypatch):
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "초안")
    card = store.pages(page_type="measure")[0]
    s = assist_mod.suggest(card, cfg=_cfg("grok"), task="concept", provider="external")
    assert s.provider == "grok" and s.external is True
    assert s.requested == "grok"


def test_internal_choice_is_honoured_even_when_grade_allows_external(wiki, monkeypatch):
    """사용자의 선택이 더 좁으면 그대로 따른다 — 넓히는 방향으로만 서버가 개입한다."""
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "초안")
    card = store.pages(page_type="measure")[0]
    s = assist_mod.suggest(card, cfg=_cfg("grok"), task="concept", provider="internal")
    assert s.provider == "ollama" and s.external is False


def test_grade_overrides_the_choice_and_says_so(wiki, monkeypatch):
    """confidential 페이지에 외부를 골라도 사내로 간다. 그리고 그 사실을 알린다."""
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "초안")
    page = store.pages(page_type="diagnosis")[0]
    s = assist_mod.suggest(page, cfg=_cfg("grok"), task="concept", provider="external")
    assert s.provider == "ollama" and s.external is False
    assert s.requested == "grok"
    assert s.to_dict()["overridden"] is True
    assert any("고른 경로" in w for w in s.warnings)


def test_invented_numbers_are_caught_in_the_output(wiki, monkeypatch):
    """프롬프트로만 막으면 언젠가 샌다. 출력에서 다시 본다."""
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "회수기간은 2.8년으로 추정되며 절감률은 47.3% 수준이다.")
    card = store.pages(page_type="measure")[0]
    s = assist_mod.suggest(card, cfg=_cfg("grok"), task="concept", provider="external")
    assert not s.numeric_clean
    assert "2.8" in s.invented_numbers
    assert s.warnings


def test_quoting_existing_numbers_is_clean(wiki, monkeypatch):
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    card = store.pages(page_type="measure")[0]
    known = sorted(assist_mod.numbers_in(card.body), key=len, reverse=True)[:2]
    _patch_provider(monkeypatch, f"원문 값 {known[0]} 과 {known[1]} 을 그대로 인용한다.")
    s = assist_mod.suggest(card, cfg=_cfg("grok"), task="concept", provider="external")
    assert s.numeric_clean


def test_prompt_forbids_generating_numbers(wiki, monkeypatch):
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "초안")
    card = store.pages(page_type="measure")[0]
    assist_mod.suggest(card, cfg=_cfg("grok"), task="concept", provider="external")
    assert "숫자를 새로 만들지 마라" in _StubProvider.last["system"]


def test_unknown_task_is_rejected(wiki, monkeypatch):
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "초안")
    with pytest.raises(assist_mod.AssistError):
        assist_mod.suggest(store.pages()[0], cfg=_cfg(), task="아무거나")


# --------------------------------------------------------------------------- #
# 재분석 — 원문 발췌를 근거로 서술만 다시 쓴다
# --------------------------------------------------------------------------- #
def _cited_card(store):
    """근거 쪽이 있는 개선안 카드 하나."""
    return next(p for p in store.pages(page_type="measure")
                if (p.source_span[0].get("pages") or []))


def _chunks_for(card) -> list[dict]:
    """카드가 인용한 쪽 + 인용하지 않은 쪽. 둘을 섞어 두어야 필터가 검증된다."""
    cited = (card.source_span[0].get("pages") or [])[0]
    return [
        {"page": cited, "channel": "text",
         "content": "저효율 루츠블로워 28대를 철거하고 회전식 디스크 건조기를 설치한다."},
        {"page": 999, "channel": "table", "content": "집계표 — 인용하지 않은 쪽의 표다."},
    ]


def test_excerpt_takes_only_the_cited_pages(wiki):
    """문서 전체를 넣으면 모델이 엉뚱한 쪽을 근거로 쓴다."""
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    card = _cited_card(store)
    text = assist_mod.source_excerpt(card, _chunks_for(card))
    assert "루츠블로워 28대" in text
    assert "집계표" not in text, "인용하지 않은 쪽이 근거로 들어갔다"


def test_reanalyze_sends_the_excerpt_to_the_model(wiki, monkeypatch):
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "# 제목\n\n## 요약\n다시 쓴 문장.\n\n## 관련\n—")
    card = _cited_card(store)
    assist_mod.reanalyze(card, cfg=_cfg("grok"), chunks=_chunks_for(card), provider="external")
    assert "원문 발췌" in _StubProvider.last["prompt"]
    assert "루츠블로워 28대" in _StubProvider.last["prompt"]


def test_reanalyze_without_context_says_so(wiki, monkeypatch):
    """근거 없이 다시 쓰면 문장만 매끄러워지고 맥락은 그대로 빈다 — 그 사실을 알린다."""
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "# 제목\n\n## 요약\n다시 쓴 문장.")
    card = store.pages(page_type="measure")[0]
    s = assist_mod.reanalyze(card, cfg=_cfg("grok"), chunks=[], provider="external")
    assert any("원문 발췌를 찾지 못해" in w for w in s.warnings)


def test_reanalyze_flags_broken_structure(wiki, monkeypatch):
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    _patch_provider(monkeypatch, "제목도 절도 없는 한 문단짜리 답변.")
    card = store.pages(page_type="measure")[0]
    s = assist_mod.reanalyze(card, cfg=_cfg("grok"), chunks=_chunks_for(card),
                             provider="external")
    assert any("절 구조" in w for w in s.warnings)
    assert s.decision["structure_kept"] is False


def test_structure_check_accepts_a_faithful_rewrite(wiki):
    from llmwiki.ediag import assist as assist_mod

    store, _ = wiki
    card = store.pages(page_type="measure")[0]
    ok, missing = assist_mod.structure_kept(card.body, card.body.replace("이 진단에서", "본 진단에서"))
    assert ok and not missing
