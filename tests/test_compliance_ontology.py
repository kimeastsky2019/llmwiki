"""규제 온톨로지와 근거 검증 — 스키마 불변식을 테스트로 고정한다.

여기 있는 테스트 중 몇 개는 성능이 아니라 **설계 결정**을 지킨다.
조문 앵커, 권한 3분할, 삭제 없음 — 이것들이 코드에서 조용히 풀리면
2년 뒤에 전면 재구축이 된다.
"""

from __future__ import annotations

import json

import pytest

from llmwiki.compliance.ontology import (
    COMPLIANCE_ONTOLOGY_VERSION,
    DEFERRAL_TRIGGERS,
    EDGE_TYPES,
    NODE_TYPES,
    VERDICT_LABELS,
    VERDICTS,
    edge_key,
    node_id,
    schema_dict,
    type_of,
)
from llmwiki.compliance.spans import (
    FORCE_MAY,
    FORCE_MUST,
    FORCE_SHOULD,
    Span,
    check_citation_force,
    force_of,
    locate_quote,
    split_articles,
    verify_span,
)


# --------------------------------------------------------------------------- #
# 스키마
# --------------------------------------------------------------------------- #
def test_schema_is_json_serializable():
    payload = json.loads(json.dumps(schema_dict(), ensure_ascii=False))
    assert payload["ontology"] == COMPLIANCE_ONTOLOGY_VERSION
    assert set(payload["nodes"]) == set(NODE_TYPES)
    assert set(payload["edges"]) == set(EDGE_TYPES)


def test_edge_domain_and_range_reference_declared_nodes():
    for edge in EDGE_TYPES.values():
        for side in (*edge.domain, *edge.range):
            assert side in NODE_TYPES, f"{edge.name}: 정의되지 않은 노드 타입 {side}"


def test_node_id_parts_are_declared_properties():
    for node in NODE_TYPES.values():
        for part in node.id_parts:
            assert part in node.properties, f"{node.name}: id_parts 의 {part} 가 속성에 없다"


def test_edge_key_props_are_declared_properties():
    for edge in EDGE_TYPES.values():
        for part in edge.key_props:
            assert part in edge.properties, f"{edge.name}: key_props 의 {part} 가 속성에 없다"


def test_every_verdict_has_a_korean_label():
    assert set(VERDICT_LABELS) == set(VERDICTS)


def test_deferral_triggers_are_documented():
    assert len(DEFERRAL_TRIGGERS) >= 7
    assert all(note for note in DEFERRAL_TRIGGERS.values())


# --------------------------------------------------------------------------- #
# ★ 단일 실패 지점 — 조문 앵커
# --------------------------------------------------------------------------- #
def test_provision_id_is_an_immutable_uuid_not_an_article_number():
    """법령 번호를 식별자로 쓰면 개정 한 번에 전 매핑이 깨진다.

    이 테스트가 깨졌다면 누군가 Provision 의 ID 규칙에 number 를 넣은 것이다.
    성능 문제가 아니라 프로젝트 전체가 무너지는 변경이다.
    """
    provision = NODE_TYPES["Provision"]
    assert provision.anchor is True
    assert provision.id_parts == ("uuid",)
    assert "number" in provision.required   # 번호는 남기되 속성이다
    assert "number" not in provision.id_parts


def test_anchor_types_are_keyed_by_uuid_only():
    for node in NODE_TYPES.values():
        if node.anchor:
            assert node.id_parts == ("uuid",), f"{node.name}: 앵커는 UUID 한 개여야 한다"


def test_split_into_lineage_exists_for_provisions():
    """조문이 분화해도 계보로 따라갈 수 있어야 한다."""
    spec = EDGE_TYPES["SPLIT_INTO"]
    assert spec.domain == ("Provision",) and spec.range == ("Provision",)


# --------------------------------------------------------------------------- #
# 권한 3분할
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["Assessment", "Service", "RuleSet", "Agent"])
def test_model_cannot_propose_judgement_or_org_facts(name):
    assert NODE_TYPES[name].llm_proposable is False


def test_assessment_derivation_is_rule():
    """판정 노드의 기본 근거는 룰이다. 모델이 아니다."""
    assert NODE_TYPES["Assessment"].derivation == "rule"


def test_staging_types_never_belong_to_the_approved_graph():
    staging = {n.name for n in NODE_TYPES.values() if n.staging}
    assert staging == {"ChangeSet", "RegChange"}


def test_document_derived_types_require_spans():
    for name in ("Provision", "Obligation"):
        assert NODE_TYPES[name].requires_span is True
    for name in ("DERIVES", "SATISFIED_BY"):
        assert EDGE_TYPES[name].requires_span is True


# --------------------------------------------------------------------------- #
# 식별자
# --------------------------------------------------------------------------- #
def test_node_id_is_deterministic():
    a = node_id("Control", code="ACC-01")
    b = node_id("Control", code="ACC-01")
    assert a == b == "ctrl:ACC-01"


def test_node_id_rejects_missing_parts():
    with pytest.raises(ValueError):
        node_id("Provision", number="제3조")


def test_type_of_recovers_the_node_type():
    assert type_of(node_id("Provision", uuid="x")) == "Provision"
    assert type_of("nope:1") is None


def test_satisfied_by_edges_are_distinct_per_service():
    """같은 통제·같은 증적이라도 서비스가 다르면 다른 엣지다."""
    a = edge_key("SATISFIED_BY", "ctrl:ACC-01", "evd:1", {"service_uuid": "svc-credit-scoring"})
    b = edge_key("SATISFIED_BY", "ctrl:ACC-01", "evd:1", {"service_uuid": "svc-call-summary"})
    assert a != b


# --------------------------------------------------------------------------- #
# 근거 스팬 — 환각을 막는 첫 겹
# --------------------------------------------------------------------------- #
TEXT = "제3조(책임) ① 금융회사는 책임관계를 문서로 명시하여야 한다."


def test_span_of_cannot_disagree_with_the_source():
    span = Span.of("doc", TEXT, 13, len(TEXT))
    assert span.quote == TEXT[13:]
    assert verify_span(span, {"doc": TEXT}).ok


def test_fabricated_quote_is_rejected():
    """모델이 그럴듯한 문장을 지어내면 오프셋이 맞지 않아 여기서 죽는다."""
    span = Span(doc_id="doc", start=0, end=20, quote="금융회사는 반드시 보험에 가입하여야 한다")
    check = verify_span(span, {"doc": TEXT})
    assert not check.ok
    assert any(i.code == "span.mismatch" for i in check.issues)


def test_span_pointing_past_the_document_is_rejected():
    span = Span(doc_id="doc", start=0, end=9999, quote="x")
    assert not verify_span(span, {"doc": TEXT}).ok


WRAPPED = (
    "제5조(위험 점검) ① 금융회사는 고영향 인공지능 서비스에 대하여 연 1회 이상 위험\n"
    "점검을 실시하여야 한다.\n"
)


def test_quote_is_found_even_when_the_source_wraps_the_line():
    """법령 원문은 한 문장이 여러 줄에 걸쳐 있고, 모델은 한 줄로 옮겨 적는다."""
    quote = "금융회사는 고영향 인공지능 서비스에 대하여 연 1회 이상 위험 점검을 실시하여야 한다."
    assert quote not in WRAPPED                    # 글자 그대로는 없다
    found = locate_quote(WRAPPED, quote)
    assert found is not None
    span = Span.of("doc", WRAPPED, *found)
    assert "\n" in span.quote                      # 저장되는 것은 원문 쪽이다
    assert verify_span(span, {"doc": WRAPPED}).ok  # 엄격한 대조를 그대로 통과한다


def test_loose_locating_still_rejects_invented_sentences():
    """찾는 방법만 느슨해졌을 뿐, 없는 문장은 여전히 못 찾는다."""
    assert locate_quote(WRAPPED, "금융회사는 외부 기관의 검증을 받아야 한다.") is None
    assert locate_quote(WRAPPED, "   ") is None


def test_missing_document_is_reported():
    span = Span(doc_id="ghost", start=0, end=3, quote="abc")
    assert any(i.code == "span.doc" for i in verify_span(span, {"doc": TEXT}).issues)


# --------------------------------------------------------------------------- #
# 인용 강도 — 환각을 막는 둘째 겹
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ("책임관계를 문서로 명시하여야 한다.", FORCE_MUST),
        ("그러하여서는 아니 된다.", FORCE_MUST),
        # '-아야/-어야 한다' 는 '하다' 에만 붙지 않는다. 배포해서 Grok 을 물렸을 때
        # 실제로 이 형태를 놓쳐 정당한 제안이 반려됐다.
        ("담당자의 승인을 받아야 한다.", FORCE_MUST),
        ("내부 기준을 지켜야 한다.", FORCE_MUST),
        ("요건을 갖추어야 한다.", FORCE_MUST),
        ("보존 기간을 두어야 하며", FORCE_MUST),
        ("공개하도록 노력하여야 한다.", FORCE_SHOULD),   # ← 필수가 아니다
        ("작성하는 것이 바람직하다.", FORCE_SHOULD),
        ("자료를 제출할 수 있다.", FORCE_MAY),
        ("이 조에서 정의는 다음과 같다.", 0),
    ],
)
def test_force_reading(text, expected):
    assert force_of(text) == expected


def test_effort_clause_is_not_read_as_mandatory():
    """'노력하여야 한다' 는 '하여야 한다' 를 포함한다. 순서를 틀리면 권고가 전부 필수가 된다."""
    assert force_of("공개하도록 노력하여야 한다.") < force_of("공개하여야 한다.")


def test_claim_stronger_than_evidence_is_rejected():
    span = Span.of("doc", "금융회사는 공개하도록 노력하여야 한다.", 0, 24)
    check = check_citation_force({"level": "mandatory"}, [span], label="obl:x")
    assert not check.ok
    assert any(i.code == "citation.force" for i in check.issues)


def test_claim_within_evidence_passes():
    span = Span.of("doc", TEXT, 0, len(TEXT))
    assert check_citation_force({"level": "mandatory"}, [span]).ok
    assert check_citation_force({"level": "recommended"}, [span]).ok


def test_org_decisions_do_not_need_a_document_citation():
    """'우리는 이 증적을 요구한다' 는 문서 인용이 아니라 조직의 결정이다."""
    assert check_citation_force({"required_yn": True}, []).ok
    assert not check_citation_force({"level": "mandatory"}, []).ok


# --------------------------------------------------------------------------- #
# 조문 분할 (L0)
# --------------------------------------------------------------------------- #
SAMPLE = (
    "제1조(목적) 이 지침은 위험관리를 정한다.\n"
    "제2조(정의) 정의는 다음과 같다.\n"
    "제2조의2(적용) 적용 범위를 정한다.\n"
)


def test_split_articles_keeps_offsets_that_point_back_to_the_source():
    articles = split_articles(SAMPLE)
    assert [a["number"] for a in articles] == ["제1조", "제2조", "제2조의2"]
    for a in articles:
        assert SAMPLE[a["start"]:a["end"]].startswith(a["number"])


def test_split_articles_reads_titles():
    assert [a["title"] for a in split_articles(SAMPLE)] == ["목적", "정의", "적용"]
