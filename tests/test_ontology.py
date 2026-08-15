"""온톨로지 스키마 적합성 테스트.

스키마를 문서로만 두면 코드가 먼저 움직이고 문서가 낡는다.
여기서 '산출물이 스키마를 지키는지' 와 '그래프가 스키마 안에서만 만들어지는지'
둘 다 고정한다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from llmwiki.config import load_config
from llmwiki.indexer import scan
from llmwiki.ontology import (
    EDGE_TYPES,
    NODE_TYPES,
    ONTOLOGY_VERSION,
    build_graph,
    node_id,
    schema_dict,
    validate_index,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def index():
    return scan(load_config(ROOT / "config.yaml"))


@pytest.fixture(scope="module")
def graph(index):
    return build_graph(index, project_id="default")


# --------------------------------------------------------------------------- #
# 스키마 자체
# --------------------------------------------------------------------------- #
def test_schema_is_json_serializable():
    """스키마를 다른 도구에 넘길 수 있어야 한다."""
    payload = json.loads(json.dumps(schema_dict(), ensure_ascii=False))
    assert payload["ontology"] == ONTOLOGY_VERSION
    assert set(payload["nodes"]) == set(NODE_TYPES)
    assert set(payload["edges"]) == set(EDGE_TYPES)


def test_edge_domain_and_range_reference_declared_nodes():
    """관계가 존재하지 않는 노드 타입을 가리키면 안 된다."""
    for edge in EDGE_TYPES.values():
        for side in (*edge.domain, *edge.range):
            assert side in NODE_TYPES, f"{edge.name}: 정의되지 않은 노드 타입 {side}"


def test_node_id_parts_are_declared_properties():
    for node in NODE_TYPES.values():
        for part in node.id_parts:
            assert part in node.properties, f"{node.name}: id_parts 의 {part} 가 속성에 없다"


# --------------------------------------------------------------------------- #
# 식별자
# --------------------------------------------------------------------------- #
def test_node_id_is_deterministic():
    a = node_id("Table", project_id="default", name="TB_CUST")
    b = node_id("Table", project_id="default", name="TB_CUST")
    assert a == b == "tbl:default/TB_CUST"


def test_node_id_scopes_by_project():
    """프로젝트가 다르면 같은 FQN 이라도 다른 노드다."""
    assert node_id("Type", project_id="a", fqn="com.x.Y") != node_id(
        "Type", project_id="b", fqn="com.x.Y"
    )


def test_node_id_rejects_missing_parts():
    with pytest.raises(ValueError):
        node_id("Table", project_id="default")


# --------------------------------------------------------------------------- #
# 산출물 적합성
# --------------------------------------------------------------------------- #
def test_sample_index_conforms(index):
    result = validate_index(index)
    assert result.ok, "\n".join(str(i) for i in result.errors)


def test_validator_catches_unknown_type_kind(index):
    broken = copy.deepcopy(index)
    next(iter(broken.classes.values())).kind = "wizard"
    result = validate_index(broken)
    assert not result.ok
    assert any(i.code == "type.kind" for i in result.errors)


def test_validator_catches_lowercase_table(index):
    broken = copy.deepcopy(index)
    st = next(s for s in broken.statements.values() if s.crud)
    st.crud[0][0] = st.crud[0][0].lower()
    assert any(i.code == "table.case" for i in validate_index(broken).errors)


def test_validator_catches_dangling_edge(index):
    broken = copy.deepcopy(index)
    broken.edges.append(["com.nope.Ghost#run", "com.nope.Ghost#walk", "call"])
    assert any(i.code == "edge.domain" for i in validate_index(broken).errors)


# --------------------------------------------------------------------------- #
# 그래프
# --------------------------------------------------------------------------- #
def test_graph_uses_only_declared_types(graph):
    for node in graph["nodes"]:
        assert node["type"] in NODE_TYPES
    for edge in graph["edges"]:
        assert edge["type"] in EDGE_TYPES


def test_graph_edges_respect_domain_and_range(graph):
    kinds = {n["id"]: n["type"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        spec = EDGE_TYPES[edge["type"]]
        assert kinds[edge["source"]] in spec.domain, (
            f"{edge['type']}: 출발이 {kinds[edge['source']]} (허용 {spec.domain})"
        )
        assert kinds[edge["target"]] in spec.range, (
            f"{edge['type']}: 도착이 {kinds[edge['target']]} (허용 {spec.range})"
        )


def test_graph_has_no_dangling_edges(graph):
    ids = {n["id"] for n in graph["nodes"]}
    for edge in graph["edges"]:
        assert edge["source"] in ids and edge["target"] in ids


def test_every_fact_carries_its_derivation(graph):
    """무엇이 파서의 사실이고 무엇이 계산·서술인지 항상 구분된다."""
    for item in (*graph["nodes"], *graph["edges"]):
        assert item["derivation"] in ("static", "derived", "llm")


def test_accesses_edges_carry_crud(graph):
    accesses = [e for e in graph["edges"] if e["type"] == "accesses"]
    assert accesses, "샘플에 테이블 접근이 있어야 한다"
    assert all(e.get("crud") in ("C", "R", "U", "D") for e in accesses)


def test_impact_edges_are_symmetric_and_carry_tables(graph):
    impacts = {(e["source"], e["target"]): e for e in graph["edges"] if e["type"] == "impacts"}
    assert impacts, "샘플의 두 프로그램은 TB_CUST 를 공유한다"
    for (a, b), edge in impacts.items():
        assert (b, a) in impacts, "영향도는 양방향으로 저장한다"
        assert edge["via_tables"], "공유 테이블이 비어 있으면 안 된다"


def test_graph_is_stable_across_runs(index):
    """같은 소스 → 같은 그래프. 두 시점 비교(diff)의 전제."""
    first = build_graph(index, project_id="default")
    second = build_graph(index, project_id="default")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
