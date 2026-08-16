"""분석·컨설팅 (L5) — 기존 방식으로는 아예 불가능했던 것들.

자동 판정률은 그래프를 깔아도 크게 오르지 않는다. 진짜 가치는 여기다.

* **커버리지 갭** — 통제가 연결되지 않은 규제 의무. 그래프만 있으면 나오고,
  경영진 보고에 그대로 쓸 수 있다. "우리가 통제하지 않고 있는 의무 N건."
* **규제 변경 영향분석** — 조문 하나가 개정되면 어떤 통제·판정·서비스가 흔들리는지.
* **수기 의존 통제** — 증적을 만들어 내는 시스템 기능이 없는 통제. 자동화 후보다.
  LLMWiki 가 운영 소스에서 뽑은 Program 이 여기 붙는다.
* **기준 변경 사전 영향 평가** — 임계치를 바꾸면 몇 건이 뒤집히는지 병합 전에 계산.

전부 결정론적 그래프 조회다. 모델이 끼지 않는다.
"""

from __future__ import annotations

from typing import Any, Iterable

from .ontology import node_id
from .store import Graph

# --------------------------------------------------------------------------- #
# 역방향 도달 — 무엇이 무엇에 닿는가
# --------------------------------------------------------------------------- #
def affected_controls(graph: Graph, node_idents: Iterable[str]) -> set[str]:
    """건드린 노드들에서 하류로 내려가 닿는 통제 집합."""
    controls: set[str] = set()
    for ident in node_idents:
        node = graph.node(ident)
        if node is None:
            continue
        kind = node["type"]
        if kind == "Control":
            controls.add(ident)
        elif kind == "Obligation":
            controls.update(graph.targets(ident, "IMPLEMENTED_BY"))
        elif kind == "Provision":
            for obl in graph.targets(ident, "DERIVES"):
                controls.update(graph.targets(obl, "IMPLEMENTED_BY"))
        elif kind == "Regulation":
            for prv in graph.targets(ident, "HAS_PROVISION"):
                for obl in graph.targets(prv, "DERIVES"):
                    controls.update(graph.targets(obl, "IMPLEMENTED_BY"))
        elif kind == "TestProcedure":
            controls.update(graph.sources(ident, "VERIFIED_BY"))
        elif kind == "Evidence":
            controls.update(graph.sources(ident, "PRODUCES"))
            controls.update(graph.sources(ident, "SATISFIED_BY"))
        elif kind == "SystemFunction":
            for evd in graph.sources(ident, "COLLECTED_FROM"):
                controls.update(graph.sources(evd, "PRODUCES"))
    return controls


def services_of(graph: Graph, control_idents: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for ctrl in control_idents:
        out.update(graph.targets(ctrl, "APPLIES_TO"))
    return out


def assessments_of(graph: Graph, control_idents: Iterable[str]) -> list[dict[str, Any]]:
    codes = {graph.props(c).get("code") for c in control_idents}
    return [
        a for a in graph.of_type("Assessment")
        if a["props"].get("control_code") in codes
    ]


# --------------------------------------------------------------------------- #
# 커버리지 갭
# --------------------------------------------------------------------------- #
def coverage_gap(graph: Graph) -> dict[str, Any]:
    """통제되지 않는 의무, 증적 없는 통제, 절차 없는 통제, 수기 의존 통제."""
    uncovered: list[dict[str, Any]] = []
    for obl in graph.of_type("Obligation"):
        controls = graph.targets(obl["id"], "IMPLEMENTED_BY")
        if controls:
            continue
        provisions = [graph.props(p) for p in graph.sources(obl["id"], "DERIVES")]
        uncovered.append({
            "obligation": obl["id"],
            "title": obl["props"].get("title"),
            "level": obl["props"].get("level"),
            "provisions": [f"{p.get('number')} {p.get('title', '')}".strip()
                           for p in provisions],
        })

    partial: list[dict[str, Any]] = []
    for edge in graph.active_edges():
        if edge["type"] != "IMPLEMENTED_BY":
            continue
        mapping = edge["props"].get("mapping_type")
        if mapping in ("subset-of", "intersects-with"):
            partial.append({
                "obligation": edge["source"],
                "title": graph.props(edge["source"]).get("title"),
                "control": graph.props(edge["target"]).get("code"),
                "mapping_type": mapping,
                "note": "통제가 의무를 일부만 덮는다",
            })

    no_evidence: list[dict[str, Any]] = []
    no_procedure: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    for ctrl in graph.of_type("Control"):
        code = ctrl["props"].get("code")
        required = [
            e["target"] for e in graph.out_edges(ctrl["id"], "PRODUCES")
            if graph.props(e["target"]).get("required_yn") is True
        ]
        if not required:
            no_evidence.append({"control": code, "title": ctrl["props"].get("title")})
        if not graph.targets(ctrl["id"], "VERIFIED_BY"):
            no_procedure.append({"control": code, "title": ctrl["props"].get("title")})
        if required and not any(graph.targets(e, "COLLECTED_FROM") for e in required):
            manual.append({
                "control": code, "title": ctrl["props"].get("title"),
                "note": "증적을 생산하는 시스템 기능이 없다 — 수기 의존, 자동화 후보",
            })

    return {
        "uncovered_obligations": uncovered,
        "partially_covered": partial,
        "controls_without_evidence": no_evidence,
        "controls_without_procedure": no_procedure,
        "manual_controls": manual,
        "summary": {
            "obligations": len(graph.of_type("Obligation")),
            "uncovered": len(uncovered),
            "partially_covered": len(partial),
            "controls": len(graph.of_type("Control")),
            "controls_without_evidence": len(no_evidence),
            "manual_controls": len(manual),
        },
    }


# --------------------------------------------------------------------------- #
# 규제 변경 영향분석
# --------------------------------------------------------------------------- #
def provision_impact(graph: Graph, provision_uuid: str) -> dict[str, Any]:
    """조문 하나가 개정되면 무엇이 흔들리는가."""
    prv_id = node_id("Provision", uuid=provision_uuid)
    node = graph.node(prv_id)
    if node is None:
        raise KeyError(f"조문을 찾을 수 없다: {provision_uuid}")

    obligations = graph.targets(prv_id, "DERIVES")
    controls = affected_controls(graph, [prv_id])
    services = services_of(graph, controls)
    assessments = assessments_of(graph, controls)
    lineage = _lineage(graph, prv_id)

    return {
        "provision": {
            "uuid": provision_uuid,
            "number": node["props"].get("number"),
            "title": node["props"].get("title"),
            "status": node["status"],
        },
        "lineage": lineage,
        "obligations": [
            {"id": o, "title": graph.props(o).get("title"),
             "level": graph.props(o).get("level")}
            for o in obligations
        ],
        "controls": sorted(filter(None, (graph.props(c).get("code") for c in controls))),
        "services": sorted(filter(None, (graph.props(s).get("name") for s in services))),
        "assessments": len(assessments),
        "confirmed_assessments": len(
            [a for a in assessments if a["props"].get("decision_status") == "확정"]
        ),
    }


def _lineage(graph: Graph, prv_id: str) -> list[str]:
    """분화·대체 계보. 번호가 밀려도 여기로 따라간다."""
    out: list[str] = []
    for target in graph.targets(prv_id, "SPLIT_INTO"):
        out.append(f"SPLIT_INTO → {graph.props(target).get('number')}")
    for target in graph.targets(prv_id, "REPLACED_BY"):
        out.append(f"REPLACED_BY → {graph.props(target).get('number')}")
    for source in graph.sources(prv_id, "SPLIT_INTO"):
        out.append(f"← SPLIT_INTO {graph.props(source).get('number')}")
    return out


# --------------------------------------------------------------------------- #
# 연계 — LLMWiki 가 뽑은 운영 소스와 잇는다
# --------------------------------------------------------------------------- #
def system_function_links(graph: Graph) -> dict[str, Any]:
    """증적 생산 기능이 실제 운영 프로그램과 연결돼 있는지."""
    linked: list[dict[str, Any]] = []
    orphan: list[dict[str, Any]] = []
    for fn in graph.of_type("SystemFunction"):
        row = {
            "key": fn["props"].get("key"),
            "name": fn["props"].get("name"),
            "system": fn["props"].get("system"),
            "program_ref": fn["props"].get("program_ref", ""),
            "evidences": len(graph.sources(fn["id"], "COLLECTED_FROM")),
        }
        (linked if row["program_ref"] else orphan).append(row)
    return {
        "linked": linked, "unlinked": orphan,
        "summary": {"linked": len(linked), "unlinked": len(orphan)},
    }


# --------------------------------------------------------------------------- #
# 요약
# --------------------------------------------------------------------------- #
def overview(graph: Graph) -> dict[str, Any]:
    gap = coverage_gap(graph)
    return {
        "version": graph.version,
        "counts": graph.counts(),
        "coverage": gap["summary"],
        "system_functions": system_function_links(graph)["summary"],
    }
