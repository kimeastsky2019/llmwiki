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

from . import i18n
from .ontology import CONFIRMED, node_id
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
def coverage_gap(graph: Graph, *, lang: str = i18n.DEFAULT_LANG) -> dict[str, Any]:
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
                "note": i18n.t(i18n.COVERAGE, lang, "partial"),
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
                "note": i18n.t(i18n.COVERAGE, lang, "manual"),
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
            [a for a in assessments if a["props"].get("decision_status") == CONFIRMED]
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


# --------------------------------------------------------------------------- #
# 서비스 축 — 화면의 출발점
# --------------------------------------------------------------------------- #
#: 서비스 하나가 지나는 단계. 화면의 진행바가 이 코드를 그대로 그린다.
#: 각 단계는 "앞의 것이 없으면 뒤의 것이 의미가 없다" 는 순서다.
SERVICE_STAGES: tuple[str, ...] = (
    "define",     # ② 서비스 정의 — 프로그램 묶음
    "grade",      # ③ 위험등급 산정
    "controls",   # ④ 통제·증적 매핑
    "assess",     # ⑤ 자동 판정
    "confirm",    # ⑥ 결재·확정
    "done",
)


def service_functions(graph: Graph, service_ident: str) -> list[dict[str, Any]]:
    """서비스를 이루는 증적 생산 기능과, 그것이 가리키는 운영 프로그램."""
    out: list[dict[str, Any]] = []
    for fn in graph.targets(service_ident, "REALIZED_BY"):
        props = graph.props(fn)
        ref = str(props.get("program_ref", ""))
        # prog:<project>/<program_id> — 참조 문자열을 쪼개는 곳을 여기 하나로 둔다.
        project, _, program_id = ref[5:].partition("/") if ref.startswith("prog:") else ("", "", "")
        out.append({
            "key": props.get("key"),
            "name": props.get("name"),
            "system": props.get("system"),
            "program_ref": ref,
            "project": project,
            "program_id": program_id,
            "evidences": len(graph.sources(fn, "COLLECTED_FROM")),
        })
    return sorted(out, key=lambda r: str(r["name"] or r["key"]))


def service_controls(graph: Graph, service_ident: str) -> list[dict[str, Any]]:
    """이 서비스에 걸린 통제와, 각 통제가 요구하는 증적의 생산 경로."""
    rows: list[dict[str, Any]] = []
    for ctrl in graph.sources(service_ident, "APPLIES_TO"):
        props = graph.props(ctrl)
        required = [
            e for e in graph.targets(ctrl, "PRODUCES")
            if graph.props(e).get("required_yn")
        ]
        # COLLECTED_FROM 이 없는 요구 증적 = 수기 의존 = 자동화 후보
        manual = [e for e in required if not graph.targets(e, "COLLECTED_FROM")]
        rows.append({
            "code": props.get("code"),
            "title": props.get("title"),
            "title_en": props.get("title_en", ""),
            "auto_level": props.get("auto_level"),
            "required_evidence": len(required),
            "manual_evidence": len(manual),
            "manual_titles": [str(graph.props(e).get("title", "")) for e in manual],
        })
    return sorted(rows, key=lambda r: str(r["code"]))


def service_assessments(graph: Graph, service_uuid: str) -> list[dict[str, Any]]:
    """이 서비스의 판정. 통제마다 최신 1건만 남긴다 — 화면이 세는 숫자와 맞춘다."""
    latest: dict[str, dict[str, Any]] = {}
    for node in sorted(graph.of_type("Assessment"),
                       key=lambda n: str(n["props"].get("assessed_at", ""))):
        props = node["props"]
        if str(props.get("service_uuid")) != service_uuid:
            continue
        latest[str(props.get("control_code"))] = {
            "uuid": props.get("uuid"),
            "control_code": props.get("control_code"),
            "verdict": props.get("verdict"),
            "decision_status": props.get("decision_status"),
            "assessed_at": props.get("assessed_at"),
            "reason": props.get("reason", ""),
        }
    return [latest[k] for k in sorted(latest)]


def service_row(graph: Graph, node: dict[str, Any], *, lang: str = i18n.DEFAULT_LANG) -> dict[str, Any]:
    """목록 한 줄 — 그래프에서만 나오는 값. 위험등급은 저장소 쪽이 얹는다."""
    props = node["props"]
    uuid = str(props.get("uuid", ""))
    ident = node["id"]
    functions = service_functions(graph, ident)
    controls = service_controls(graph, ident)
    assessments = service_assessments(graph, uuid)
    verdicts: dict[str, int] = {}
    for a in assessments:
        key = str(a["verdict"])
        verdicts[key] = verdicts.get(key, 0) + 1
    return {
        "uuid": uuid,
        "name": _label(props, "name", lang),
        "dept": props.get("dept", ""),
        "high_impact_yn": props.get("high_impact_yn"),
        "status": node["status"],
        "programs": len(functions),
        "controls": len(controls),
        "manual_evidence": sum(c["manual_evidence"] for c in controls),
        "assessments": len(assessments),
        "verdicts": verdicts,
        "unconfirmed": len([a for a in assessments
                            if a["decision_status"] != CONFIRMED]),
    }


def _label(props: dict[str, Any], key: str, lang: str) -> str:
    if i18n.normalize(lang) == "en" and props.get(f"{key}_en"):
        return str(props[f"{key}_en"])
    return str(props.get(key, ""))


def services(graph: Graph, *, lang: str = i18n.DEFAULT_LANG) -> list[dict[str, Any]]:
    return sorted(
        (service_row(graph, n, lang=lang) for n in graph.of_type("Service")),
        key=lambda r: str(r["name"]),
    )


def service_stage(row: dict[str, Any], *, has_grade: bool) -> str:
    """지금 이 서비스가 어느 단계에 있는가.

    화면 전체가 하나의 상태를 갖는 구조로는 "서비스 A 는 ③, 서비스 B 는 ⑥" 을
    표현할 수 없다. 그래서 단계는 서비스마다 따로 돈다.
    """
    if not row["programs"]:
        return "define"
    if not has_grade:
        return "grade"
    if not row["controls"]:
        return "controls"
    if not row["assessments"]:
        return "assess"
    if row["unconfirmed"]:
        return "confirm"
    return "done"


def service_detail(
    graph: Graph, service_uuid: str, *,
    grade: dict[str, Any] | None = None,
    pending: list[dict[str, Any]] | None = None,
    lang: str = i18n.DEFAULT_LANG,
) -> dict[str, Any]:
    """서비스 대시보드 한 판. 등급(`grade`)은 저장소에서 읽어 넘겨 준다 —
    위험등급은 그래프가 아니라 배점 파이프라인의 산출물이라 여기서 계산하지 않는다."""
    ident = node_id("Service", uuid=service_uuid)
    node = graph.node(ident)
    if node is None:
        raise KeyError(f"서비스를 찾을 수 없다: {service_uuid}")

    row = service_row(graph, node, lang=lang)
    stage = service_stage(row, has_grade=bool(grade))
    return {
        "service": {
            **row,
            "note": node["props"].get("note", ""),
        },
        "stage": stage,
        "stages": list(SERVICE_STAGES),
        "grade": grade,
        "functions": service_functions(graph, ident),
        "controls": service_controls(graph, ident),
        "assessments": service_assessments(graph, service_uuid),
        "pending_changes": pending or [],
    }
