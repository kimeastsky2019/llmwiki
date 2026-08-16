"""규제 지식그래프 · 판정 엔진 API (`/api/reg/…`).

읽기 경로와 쓰기 경로가 나뉘어 있다는 점이 중요하다.

* 조회·판정은 **승인본만** 본다. 제안이 쌓여도 여기 결과는 변하지 않는다.
* 쓰기는 커밋 결재를 거치는 것뿐이다. 그래프에 직접 쓰는 엔드포인트는 없다.
  승인(`/changes/{id}/approve`)과 확정 서명(`/assess/{uuid}/confirm`)만이
  승인 그래프를 움직이고, 둘 다 사람의 행위로 기록된다.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from ..compliance import analysis, changeset as cs, rules, verify
from ..compliance.ontology import VERDICT_KO, node_id, schema_dict
from ..compliance.store import Store
from ..config import Config

router = APIRouter(prefix="/api/reg", tags=["compliance"])

_cfg: Config | None = None


def bind(cfg: Config) -> APIRouter:
    global _cfg
    _cfg = cfg
    return router


def _store() -> Store:
    if _cfg is None:  # pragma: no cover - 서버가 항상 bind 한다
        raise HTTPException(503, "규제 저장소가 설정되지 않았다")
    return Store(_cfg.compliance_dir)


def _versions() -> tuple[str, str]:
    return (_cfg.ruleset_version if _cfg else "", _cfg.standard_version if _cfg else "")


# --------------------------------------------------------------------------- #
# 스키마 · 그래프
# --------------------------------------------------------------------------- #
@router.get("/schema")
def schema() -> dict[str, Any]:
    return schema_dict()


@router.get("/graph")
def graph(as_of: str | None = Query(None), upto_seq: int | None = Query(None)) -> dict[str, Any]:
    store = _store()
    g = store.approved(as_of=as_of, upto_seq=upto_seq)
    return {
        **analysis.overview(g),
        "seq": g.seq,
        "edges": len(g.active_edges()),
        "pending_changes": len(store.pending()),
    }


@router.get("/nodes")
def nodes(type: str = Query(..., description="노드 타입"),
          as_of: str | None = Query(None)) -> dict[str, Any]:
    g = _store().approved(as_of=as_of)
    return {"type": type, "nodes": g.of_type(type)}


@router.get("/node/{node_ident:path}")
def node(node_ident: str, as_of: str | None = Query(None)) -> dict[str, Any]:
    g = _store().approved(as_of=as_of)
    found = g.node(node_ident)
    if found is None:
        raise HTTPException(404, f"노드를 찾을 수 없다: {node_ident}")
    return {
        **found,
        "out_edges": g.out_edges(node_ident),
        "in_edges": g.in_edges(node_ident),
    }


@router.get("/validate")
def validate() -> dict[str, Any]:
    store = _store()
    result = verify.validate_graph(store.approved(), documents=store.documents())
    journal = verify.validate_journal(store)
    issues = [i.__dict__ for i in result.issues + journal.issues]
    return {
        "ok": result.ok and journal.ok,
        "errors": len(result.errors) + len(journal.errors),
        "warnings": len(result.warnings),
        "issues": issues,
    }


# --------------------------------------------------------------------------- #
# 판정
# --------------------------------------------------------------------------- #
@router.get("/assess")
def assess(service: str | None = Query(None), today: str | None = Query(None),
           as_of: str | None = Query(None)) -> dict[str, Any]:
    """판정한다. LLM 을 호출하지 않는다 — 같은 그래프면 항상 같은 답이 나온다."""
    store = _store()
    g = store.approved(as_of=as_of)
    ruleset, standard = _versions()
    results = rules.adjudicate_all(
        g, service_uuid=service, ruleset_version=ruleset,
        standard_version=standard, metrics=store.metrics, today=today,
        prior=_prior(g),
    )
    return {
        "graph_seq": g.seq,
        "metrics": verify.audit_metrics(results),
        "verdict_labels": VERDICT_KO,
        "assessments": [
            {**a.to_dict(),
             "service_name": g.props(node_id("Service", uuid=a.service_uuid)).get("name", ""),
             "control_title": g.props(node_id("Control", code=a.control_code)).get("title", "")}
            for a in results
        ],
    }


@router.post("/assess/commit")
def assess_commit(service: str | None = Query(None),
                  today: str | None = Query(None)) -> dict[str, Any]:
    """판정 결과를 그래프에 남긴다 (PROV 계보 포함)."""
    store = _store()
    g = store.approved()
    ruleset, standard = _versions()
    results = rules.adjudicate_all(
        g, service_uuid=service, ruleset_version=ruleset, standard_version=standard,
        metrics=store.metrics, today=today, prior=_prior(g),
    )
    written = rules.commit(store, results, ruleset_version=ruleset)
    return {"assessments": len(results), "records": written}


@router.post("/assess/{assessment_uuid}/confirm")
def assess_confirm(assessment_uuid: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """확정 서명 (게이트 3). 자동 판정도 이 서명 전에는 잠정이다."""
    agent = str(payload.get("by", "")).strip()
    if not agent:
        raise HTTPException(400, "확정 서명자(by)가 필요하다")
    try:
        return rules.confirm(
            _store(), assessment_uuid, agent_id=agent,
            verdict=payload.get("verdict"), note=str(payload.get("note", "")),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/goldset")
def goldset(today: str | None = Query(None)) -> dict[str, Any]:
    store = _store()
    cases = store.goldset
    if not cases:
        raise HTTPException(404, "골드셋이 없다")
    ruleset, _ = _versions()
    report = verify.run_goldset(
        store.approved(), cases, metrics=store.metrics,
        ruleset_version=ruleset, today=today,
    )
    return report.to_dict()


# --------------------------------------------------------------------------- #
# 분석
# --------------------------------------------------------------------------- #
@router.get("/coverage")
def coverage() -> dict[str, Any]:
    return analysis.coverage_gap(_store().approved())


@router.get("/impact/{provision_uuid}")
def impact(provision_uuid: str) -> dict[str, Any]:
    try:
        return analysis.provision_impact(_store().approved(), provision_uuid)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/system-functions")
def system_functions() -> dict[str, Any]:
    return analysis.system_function_links(_store().approved())


# --------------------------------------------------------------------------- #
# 커밋 결재
# --------------------------------------------------------------------------- #
@router.get("/changes")
def changes(status: str | None = Query(None)) -> dict[str, Any]:
    rows = list(_store().read_changesets().values())
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("changeset_id", ""))
    return {"grades": cs.GRADES, "changes": rows}


@router.get("/changes/{changeset_id}")
def change_detail(changeset_id: str) -> dict[str, Any]:
    store = _store()
    raw = store.changeset(changeset_id)
    if raw is None:
        raise HTTPException(404, f"변경 제안을 찾을 수 없다: {changeset_id}")
    change = cs.ChangeSet.from_dict(raw)
    payload: dict[str, Any] = {**raw, "approver": cs.GRADES[change.grade]["approver"]}
    if change.status in (cs.PENDING, cs.BLOCKED):
        payload["diff"] = cs.diff(store, change)
    return payload


@router.post("/changes/{changeset_id}/approve")
def change_approve(changeset_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    approver = str(payload.get("by", "")).strip()
    if not approver:
        raise HTTPException(400, "결재자(by)가 필요하다")
    try:
        change = cs.approve(_store(), changeset_id, approver=approver,
                            note=str(payload.get("note", "")))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return change.to_dict()


@router.post("/changes/{changeset_id}/reject")
def change_reject(changeset_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    reviewer = str(payload.get("by", "")).strip()
    if not reviewer:
        raise HTTPException(400, "반려자(by)가 필요하다")
    try:
        change = cs.reject(_store(), changeset_id, reviewer=reviewer,
                           note=str(payload.get("note", "")))
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return change.to_dict()


def _prior(g: Any) -> dict[str, dict[str, str]]:
    prior: dict[str, dict[str, str]] = {}
    for node in sorted(g.of_type("Assessment"),
                       key=lambda n: str(n["props"].get("assessed_at", ""))):
        props = node["props"]
        svc, code = props.get("service_uuid"), props.get("control_code")
        if svc and code:
            prior.setdefault(str(svc), {})[str(code)] = str(props.get("verdict"))
    return prior
