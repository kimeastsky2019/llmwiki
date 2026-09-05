"""규제 지식그래프 · 판정 엔진 API (`/api/reg/…`).

읽기 경로와 쓰기 경로가 나뉘어 있다는 점이 중요하다.

* 조회·판정은 **승인본만** 본다. 제안이 쌓여도 여기 결과는 변하지 않는다.
* 쓰기는 커밋 결재를 거치는 것뿐이다. 그래프에 직접 쓰는 엔드포인트는 없다.
  승인(`/changes/{id}/approve`)과 확정 서명(`/assess/{uuid}/confirm`)만이
  승인 그래프를 움직이고, 둘 다 사람의 행위로 기록된다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from ..compliance import advise as advisor
from ..compliance import analysis, approval, changeset as cs, codehints, propose, riskassess, rules, verify
from ..compliance import i18n
from ..compliance.ontology import (
    AUTO_LEVELS,
    OPERATORS,
    PROCEDURE_KINDS,
    node_id,
    schema_dict,
)
from ..compliance.store import Store, now_iso
from ..llm import check as check_provider
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
def schema(lang: str | None = Query(None)) -> dict[str, Any]:
    lg = i18n.normalize(lang)
    # 유보 사유 설명과 판정 라벨은 화면이 그대로 찍는다 — 요청 언어로 내려 준다.
    return {
        **schema_dict(),
        "deferral_triggers": dict(i18n.TRIGGER[lg]),
        "verdict_labels": i18n.verdict_labels(lg),
        "level_labels": dict(i18n.LEVEL[lg]),
        "decision_labels": dict(i18n.DECISION[lg]),
    }


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
           as_of: str | None = Query(None),
           lang: str | None = Query(None)) -> dict[str, Any]:
    """판정한다. LLM 을 호출하지 않는다 — 같은 그래프면 항상 같은 답이 나온다."""
    store = _store()
    g = store.approved(as_of=as_of)
    ruleset, standard = _versions()
    results = rules.adjudicate_all(
        g, service_uuid=service, ruleset_version=ruleset,
        standard_version=standard, metrics=store.metrics, today=today,
        prior=_prior(g), lang=i18n.normalize(lang),
    )
    return {
        "graph_seq": g.seq,
        "metrics": verify.audit_metrics(results),
        "verdict_labels": i18n.verdict_labels(i18n.normalize(lang)),
        "assessments": [
            {**a.to_dict(),
             "service_name": _pick(
                 g.props(node_id("Service", uuid=a.service_uuid)), "name", lang),
             "control_title": _pick(
                 g.props(node_id("Control", code=a.control_code)), "title", lang)}
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
def coverage(lang: str | None = Query(None)) -> dict[str, Any]:
    return analysis.coverage_gap(_store().approved(), lang=i18n.normalize(lang))


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
# 서비스 — 두 갈래가 붙는 자리
#
# 규제는 프로그램이 아니라 AI 서비스 단위로 묻는다. 그런데 지금까지 서비스는
# 손으로 등록하는 이름 하나였고, 이미 분석해 둔 운영 프로그램과 이어지지 않았다.
# 여기서 그 다리를 화면이 건널 수 있게 연다 — CLI `reg link-programs` 하나뿐이던
# 경로가 API 가 된다.
#
# 쓰기는 여전히 결재를 거친다. 서비스 정의도 ChangeSet 으로 올라가고,
# 승인돼야 그래프에 들어간다. 사람이 한 일이라고 저널에 직접 쓰지 않는 이유는,
# "무엇이 언제 왜 들어왔나" 를 묻는 자리가 결재함 하나로 유지돼야 하기 때문이다.
# --------------------------------------------------------------------------- #
@router.get("/programs")
def programs(project: str | None = Query(None)) -> dict[str, Any]:
    """서비스로 묶을 후보 — 정적 분석이 뽑아 둔 운영 프로그램.

    이미 어느 서비스에 묶였는지도 함께 준다. 화면이 같은 프로그램을 두 서비스에
    넣기 전에 보여 줘야 한다.
    """
    idx = _index(project)
    if idx is None:
        return {"programs": [], "project": project or "", "note": "분석된 소스가 없다"}

    graph = _store().approved()
    taken: dict[str, list[str]] = {}
    for node in graph.of_type("Service"):
        row_uuid = str(node["props"].get("uuid", ""))
        for fn in analysis.service_functions(graph, node["id"]):
            if fn["program_id"]:
                taken.setdefault(str(fn["program_id"]), []).append(row_uuid)

    rows = []
    for program in idx.programs:
        rows.append({
            "id": program.id,
            "name": program.name,
            "layer": program.layer,
            "tier": program.tier,
            "urls": list(program.urls),
            "tables": list(program.tables),
            "classes": len(program.classes),
            "sql": len(program.sql_ids),
            "services": taken.get(program.id, []),
        })
    return {"programs": rows, "project": getattr(idx, "project", "")}


@router.get("/services")
def services(lang: str | None = Query(None)) -> dict[str, Any]:
    """서비스 목록 — 화면의 새 출발점. 서비스마다 단계가 따로 돈다."""
    store = _store()
    graph = store.approved()
    saved = store.read_json(RISK_FILE, default={}) or {}
    rows = []
    for row in analysis.services(graph, lang=i18n.normalize(lang)):
        grade = _grade_of(saved, row["uuid"])
        rows.append({**row, "grade": grade,
                     "stage": analysis.service_stage(row, has_grade=bool(grade))})
    return {"services": rows, "stages": list(analysis.SERVICE_STAGES),
            "pending": len([c for c in store.read_changesets().values()
                            if c.get("status") == cs.PENDING])}


def _change_summary(change: dict[str, Any]) -> str:
    """결재 건을 한 줄로. ChangeSet 에는 설명 필드가 없다 — 무엇을 하는지는
    ops 에서 읽어 낸다. 없는 제목을 지어내는 것보다 실제로 하는 일을 세는 쪽이
    결재자에게 쓸모 있다."""
    made: dict[str, int] = defaultdict(int)
    edges = 0
    for op in change.get("ops", []):
        if op.get("op") == "node.create":
            made[str(op.get("node_type", "?"))] += 1
        elif op.get("op") == "edge.create":
            edges += 1
    parts = [f"{k} {n}" for k, n in sorted(made.items())]
    if edges:
        parts.append(f"관계 {edges}")
    return " · ".join(parts) or str(change.get("changeset_id", ""))


@router.get("/process")
def process_view(lang: str | None = Query(None)) -> dict[str, Any]:
    """업무 프로세스 한 판 — 단계별 적체와 지금 손댈 것.

    ★ 이 화면의 규칙 하나: **없는 숫자는 만들지 않는다.**
    목업에는 SLA·리드타임 같은 칸이 있지만, 우리가 실제로 시각을 기록하는 것은
    결재(ChangeSet 의 created_at·reviewed_at)뿐이다. 그래서 리드타임은 승인된
    결재에서만 계산하고, 표본이 없으면 `null` 로 내보내 화면이 '미측정' 이라
    말하게 한다. 0 이나 임의값을 넣으면 그 숫자가 근거가 되어 버린다.
    """
    store = _store()
    graph = store.approved()
    saved = store.read_json(RISK_FILE, default={}) or {}
    lang_n = i18n.normalize(lang)

    # --- 단계별 적체 --- #
    per_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    high_risk = 0
    for row in analysis.services(graph, lang=lang_n):
        grade = _grade_of(saved, row["uuid"])
        stage = analysis.service_stage(row, has_grade=bool(grade))
        per_stage[stage].append({"uuid": row["uuid"], "name": row["name"],
                                 "grade": (grade or {}).get("label", "")})
        if (grade or {}).get("key") in ("high", "unacceptable"):
            high_risk += 1

    stages = [
        {"key": key, "services": per_stage.get(key, []), "count": len(per_stage.get(key, []))}
        for key in analysis.SERVICE_STAGES
    ]

    # --- 결재 큐와 리드타임 --- #
    changes = list(store.read_changesets().values())
    pending = [c for c in changes if c.get("status") == cs.PENDING]
    blocked = [c for c in changes if c.get("status") == cs.BLOCKED]

    spans: list[float] = []
    for c in changes:
        if c.get("status") != cs.APPROVED:
            continue
        made, seen = c.get("created_at"), c.get("reviewed_at")
        if not made or not seen:
            continue
        try:
            delta = datetime.fromisoformat(seen) - datetime.fromisoformat(made)
        except ValueError:
            continue
        spans.append(delta.total_seconds() / 86400)

    # --- 통제 충족 --- #
    ruleset, standard = _versions()
    results = rules.adjudicate_all(
        graph, ruleset_version=ruleset, standard_version=standard,
        metrics=store.metrics, prior=_prior(graph), lang=lang_n,
    )
    audit = verify.audit_metrics(results)
    satisfied = audit["by_verdict"].get(rules.SATISFIED, 0)

    # --- 지금 손댈 것 --- #
    # 순서는 '앞 단계가 막히면 뒤가 의미 없다' 는 것을 따른다. 기한이 없으므로
    # 마감 임박순으로 정렬하지 않는다 — 우리는 기한을 기록하지 않는다.
    queue: list[dict[str, Any]] = []
    for c in sorted(blocked, key=lambda x: str(x.get("changeset_id"))):
        queue.append({
            "kind": "blocked", "id": str(c.get("changeset_id", "")),
            "title": _change_summary(c),
            "owner": cs.GRADES.get(str(c.get("grade")), {}).get("approver", ""),
            "at": c.get("created_at", ""),
        })
    for c in sorted(pending, key=lambda x: str(x.get("created_at"))):
        queue.append({
            "kind": "pending", "id": str(c.get("changeset_id", "")),
            "title": _change_summary(c),
            "owner": cs.GRADES.get(str(c.get("grade")), {}).get("approver", ""),
            "at": c.get("created_at", ""),
        })
    for stage in analysis.SERVICE_STAGES:
        if stage == "done":
            continue
        for svc in per_stage.get(stage, []):
            queue.append({
                "kind": "stage", "id": svc["uuid"], "title": svc["name"],
                "stage": stage, "owner": svc["grade"], "at": "",
            })

    return {
        "stages": stages,
        "kpi": {
            "pending_changes": len(pending),
            "blocked_changes": len(blocked),
            "high_risk": high_risk,
            "auto_rate": audit["auto_rate"],
            "deferred": audit["deferred"],
            # 표본이 없으면 null — 화면이 '미측정' 이라고 말한다.
            "lead_time_days": round(sum(spans) / len(spans), 1) if spans else None,
            "lead_time_samples": len(spans),
        },
        "controls": {
            "satisfied": satisfied,
            "total": audit["total"],
            "rate": round(satisfied / audit["total"], 4) if audit["total"] else 0.0,
            "triggers": audit["by_trigger"],
        },
        "queue": queue[:12],
        "queue_total": len(queue),
    }


@router.get("/service/{service_uuid}")
def service(service_uuid: str, lang: str | None = Query(None)) -> dict[str, Any]:
    """서비스 대시보드 한 판 — 등급·충족률·유보·연결 프로그램·다음 할 일."""
    store = _store()
    saved = store.read_json(RISK_FILE, default={}) or {}
    pending = [
        {"changeset_id": c.get("changeset_id"), "status": c.get("status"),
         "grade": c.get("grade"), "created_at": c.get("created_at")}
        for c in store.read_changesets().values()
        if c.get("status") in (cs.PENDING, cs.BLOCKED)
        and _touches_service(c, service_uuid)
    ]
    try:
        return analysis.service_detail(
            store.approved(), service_uuid,
            grade=_grade_of(saved, service_uuid),
            pending=sorted(pending, key=lambda r: str(r["changeset_id"])),
            lang=i18n.normalize(lang),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/services/propose")
def service_propose(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """프로그램 묶음 → 서비스 정의 제안. **승인 그래프에 바로 쓰지 않는다.**

    제안자는 사람이다 — 서비스 경계는 업무 판단이라 sLM 이 제안할 수 없고
    (`Service`·`REALIZED_BY` 는 `llm_proposable=False`), 검증기가 그것을 막는다.
    """
    by = str(payload.get("by", "")).strip()
    if not by:
        raise HTTPException(400, "제안자(by)가 필요하다")
    name = str(payload.get("name", "")).strip()
    program_ids = [str(x) for x in (payload.get("program_ids") or [])]
    if not program_ids:
        raise HTTPException(400, "묶을 프로그램을 하나 이상 골라야 한다")

    idx = _index(payload.get("project"))
    if idx is None:
        raise HTTPException(409, "분석된 소스가 없다 — 먼저 소스를 분석해야 한다")

    store = _store()
    graph = store.approved()
    known = {str(n["props"].get("key")) for n in graph.of_type("SystemFunction")}
    try:
        result = propose.propose_service(
            idx, name=name, program_ids=program_ids,
            service_uuid=str(payload.get("service_uuid", "")).strip(),
            dept=str(payload.get("dept", "")).strip(),
            note=str(payload.get("note", "")).strip(),
            project_id=str(getattr(idx, "project", "") or "default"),
            system=str(payload.get("system", "")).strip(),
            known_functions=known,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    change = cs.stage(
        store, result.ops,
        proposer={"type": "Person", "id": by},
        source={"type": "llmwiki", "id": str(getattr(idx, "project", ""))},
    )
    return {"changeset": change.to_dict(), "note": result.note,
            "rejected": result.rejected,
            "approver": cs.GRADES[change.grade]["approver"]}


# --------------------------------------------------------------------------- #
# 프로젝트 결재 — 계획 승인과 결과 승인
#
# 기준 변경 결재(/changes)와 다른 것이다. 저쪽은 *무엇으로 잴 것인가*, 여기는
# *이 서비스를 내보내도 되는가* 를 묻는다. 회의에서 정한 대로 결재는 IT 포털
# ITSM 을 타지 않고 전부 이 시스템에서 한다.
# --------------------------------------------------------------------------- #
@router.get("/approvals")
def approvals(service: str | None = Query(None),
              role: str | None = Query(None),
              lang: str | None = Query(None)) -> dict[str, Any]:
    """결재함. `role` 을 주면 그 역할이 결정할 수 있는 건만 남긴다.

    사외 역할(제3자 검증기관)은 자기가 검증할 건만 봐야 한다 — 사내 서비스
    목록 전체가 사외에 열리면 안 된다.
    """
    store = _store()
    rows = list(approval.latest(store).values())
    if service:
        rows = [r for r in rows if r["service_uuid"] == service]

    if role == approval.VERIFIER:
        # 검증기관은 '검증이 필요하고 아직 대기 중인 건' 만 본다.
        rows = [r for r in rows
                if r.get("needs_verification") and r["status"] == approval.PENDING]
    elif role in (approval.COMMITTEE, approval.GOVERNANCE):
        rows = [r for r in rows if r["approver_role"] == role]

    names = {
        str(n["props"].get("uuid")): _pick(n["props"], "name", lang)
        for n in store.approved().of_type("Service")
    }
    rows.sort(key=lambda r: (r["status"] != approval.PENDING, str(r.get("requested_at"))))
    return {
        "approvals": [{**r, "service_name": names.get(r["service_uuid"], r["service_uuid"])}
                      for r in rows],
        "kinds": list(approval.KINDS),
    }


@router.get("/approvals/gate/{service_uuid}")
def approval_gate(service_uuid: str) -> dict[str, Any]:
    """이 서비스가 이행 가능한가. IT 포털이 물어볼 값이다."""
    return approval.gate(_store(), service_uuid)


@router.post("/approvals")
def approval_request(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """결재 상신. 등급은 저장된 위험평가에서 가져온다 — 여기서 다시 계산하지 않는다."""
    service_uuid = str(payload.get("service_uuid", "")).strip()
    store = _store()
    grade = _grade_of(store.read_json(RISK_FILE, default={}) or {}, service_uuid)
    if not grade:
        raise HTTPException(409, "위험등급이 없다 — 등급을 산정해야 결재를 올릴 수 있다")
    try:
        return approval.request(
            store, service_uuid=service_uuid,
            kind=str(payload.get("kind", "")),
            grade_key=str(grade.get("key", "")),
            grade_label=str(grade.get("label", "")),
            by=str(payload.get("by", "")),
            note=str(payload.get("note", "")).strip(),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/approvals/{approval_id}/verify")
def approval_verify(approval_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """제3자 검증 결과 등록. **승인이 아니다** — 결과를 남길 뿐이다."""
    try:
        return approval.file_verification(
            _store(), approval_id,
            by=str(payload.get("by", "")),
            result=str(payload.get("result", "")),
            note=str(payload.get("note", "")).strip(),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/approvals/{approval_id}/decide")
def approval_decide(approval_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """승인·반려. 등급이 정한 승인권자만, 상신자가 아닌 사람이 결정한다."""
    try:
        return approval.decide(
            _store(), approval_id,
            by=str(payload.get("by", "")),
            role=str(payload.get("role", "")),
            approve=bool(payload.get("approve")),
            note=str(payload.get("note", "")).strip(),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/controls")
def controls() -> dict[str, Any]:
    """평가 항목과 그 지표 — 관리자 화면이 그리는 표.

    목업의 '모니터링 지표' 표와 같은 줄을 만든다: 지표 · 산식 · 근거 법규 ·
    임계치. 여기서는 현재값과 상태를 붙이지 않는다 — 그건 서비스마다 다르고
    판정(`/assess`)이 답하는 것이라, 기준 화면이 대신 말하면 안 된다.
    """
    graph = _store().approved()

    procs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in graph.of_type("TestProcedure"):
        p = node["props"]
        procs[str(p.get("control_code"))].append({
            "seq": str(p.get("seq", "")),
            "kind": str(p.get("kind", "")),
            "metric": p.get("metric") or "",
            "operator": p.get("operator") or "",
            "threshold": p.get("threshold"),
            "unit": p.get("unit") or "",
        })

    rows: list[dict[str, Any]] = []
    for node in graph.of_type("Control"):
        p = node["props"]
        code = str(p.get("code", ""))
        mine = sorted(procs.get(code, []), key=lambda x: x["seq"])
        # 근거 법규 — 의무에서 통제로 내려오는 IMPLEMENTED_BY 를 되짚는다.
        basis = [
            {"obligation": e["source"],
             "title": str(graph.props(e["source"]).get("title")
                          or graph.props(e["source"]).get("text", ""))[:120]}
            for e in graph.in_edges(node["id"], "IMPLEMENTED_BY")
        ]
        rows.append({
            "code": code,
            "title": p.get("title", ""),
            "title_en": p.get("title_en", ""),
            "auto_level": p.get("auto_level", ""),
            "category": p.get("category", ""),
            "owner": p.get("owner", ""),
            "status": p.get("status", ""),
            "procedures": mine,
            # 임계치가 비어 있으면 판단 유보로 간다. 관리자가 고쳐야 할 자리라
            # 목록에서 바로 보이게 센다.
            "open_thresholds": sum(
                1 for x in mine if x["kind"] == "metric" and x["threshold"] in (None, "")
            ),
            "obligations": basis,
        })
    rows.sort(key=lambda r: r["code"])
    return {"controls": rows, "vocabulary": {
        "auto_level": list(AUTO_LEVELS),
        "procedure_kind": list(PROCEDURE_KINDS),
        "operator": list(OPERATORS),
    }}


@router.post("/controls/propose")
def control_propose(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """관리자가 만든 평가 항목·지표를 결재 큐에 올린다.

    ★ 그래프에 직접 쓰지 않는다. 기준을 만드는 일은 결재 없이 들어가면 안 되는
    쪽이다 — 통제 하나가 바뀌면 그 통제를 쓰는 모든 서비스의 판정이 바뀐다.
    """
    by = str(payload.get("by", "")).strip()
    if not by:
        raise HTTPException(400, "제안자(by)가 필요하다")

    store = _store()
    known = {str(n["props"].get("code")) for n in store.approved().of_type("Control")}
    try:
        result = propose.propose_control(
            code=str(payload.get("code", "")),
            title=str(payload.get("title", "")),
            auto_level=str(payload.get("auto_level", "L1")),
            category=str(payload.get("category", "")).strip(),
            owner=str(payload.get("owner", "")).strip(),
            title_en=str(payload.get("title_en", "")).strip(),
            note=str(payload.get("note", "")).strip(),
            procedures=list(payload.get("procedures") or []),
            obligations=[str(x) for x in (payload.get("obligations") or [])],
            known_controls=known,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    change = cs.stage(store, result.ops, proposer={"type": "Person", "id": by})
    return {"changeset": change.to_dict(), "note": result.note,
            "rejected": result.rejected,
            "approver": cs.GRADES[change.grade]["approver"]}


@router.post("/risk/suggest")
def risk_suggest(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """코드 근거 제안 — 프로파일 2축과 데이터·위탁 관련 위험 항목 **후보**.

    ★ 판정하지 않고, 체크하지도 않는다. 근거와 함께 제안만 하고 Yes/No 는 사람이
    누른다. `unanswerable` 로 "코드가 답할 수 없는 것" 도 같이 내려 과장을 막는다.
    """
    program_ids = [str(x) for x in (payload.get("program_ids") or [])]
    service_uuid = str(payload.get("service_uuid", "")).strip()
    project = payload.get("project")

    # 서비스만 주면 그 서비스에 묶인 프로그램을 그래프에서 찾아 온다.
    if not program_ids and service_uuid:
        graph = _store().approved()
        ident = node_id("Service", uuid=service_uuid)
        if graph.node(ident) is not None:
            fns = analysis.service_functions(graph, ident)
            program_ids = [f["program_id"] for f in fns if f["program_id"]]
            project = project or next((f["project"] for f in fns if f["project"]), None)

    return codehints.suggest(_code_facts(program_ids, project=project))


def _index(project: str | None) -> Any:
    """활성 프로젝트의 분석 인덱스. 없으면 None — 화면은 '먼저 분석하라'를 낸다."""
    try:
        from ..indexer import load_index
        from ..server.app import registry  # 지연 import — 순환을 피한다

        proj = registry.get(project)
        return load_index(registry.config_for(proj), with_source=False)
    except Exception:  # noqa: BLE001 — 인덱스가 없는 것은 오류가 아니라 상태다
        return None


def _grade_of(saved: dict[str, Any], service_uuid: str) -> dict[str, Any] | None:
    """저장된 위험평가에서 등급만 꺼낸다. 없으면 None — 아직 ③ 단계다."""
    row = saved.get(service_uuid)
    if not row:
        return None
    result = row.get("result") or {}
    return {
        "label": (result.get("final_grade") or {}).get("label", ""),
        "key": (result.get("final_grade") or {}).get("key", ""),
        "residual_score": result.get("step4_residual_score"),
        "high_impact": (result.get("step1_high_impact") or {}).get("high_impact"),
        "saved_at": row.get("saved_at", ""),
        "saved_by": row.get("saved_by", ""),
    }


def _touches_service(change: dict[str, Any], service_uuid: str) -> bool:
    """이 변경 제안이 그 서비스를 건드리는가. 대시보드의 '대기 중' 표시용."""
    ident = node_id("Service", uuid=service_uuid)
    for op in change.get("ops", []):
        if op.get("node_type") == "Service" and (op.get("props") or {}).get("uuid") == service_uuid:
            return True
        if ident in (op.get("source"), op.get("target"), op.get("id")):
            return True
        if (op.get("props") or {}).get("service_uuid") == service_uuid:
            return True
    return False


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


# --------------------------------------------------------------------------- #
# AI 위험등급 산정 (STEP 1~5)
#
# 증적 기반 통제 판정(/assess)과는 다른 파이프라인이다. 저쪽은 "이 통제가
# 충족됐나", 여기는 "이 서비스가 몇 등급인가" 를 32항목 배점으로 답한다.
# 계산은 riskassess 가 하고 여기서는 저장·조회만 한다.
# --------------------------------------------------------------------------- #
RISK_FILE = "risk_assessments.json"


@router.get("/risk/master")
def risk_master() -> dict[str, Any]:
    """배점·판정 기준. 화면이 체크리스트와 32항목 표를 이걸로 그린다."""
    m = riskassess.master()
    return {
        "version": m["version"],
        "standard": m["standard"],
        "high_impact": m["high_impact"],
        "safety": m["safety"],
        "profile_axes": m["profile_axes"],
        "evaluation_set": m["evaluation_set"],
        "mitigation_weights": m["mitigation_weights"],
        "not_mitigated_weight": m["not_mitigated_weight"],
        "grades": m["grades"],
        "high_impact_override": m["high_impact_override"],
        "rounding": m["rounding"],
        "items": m["items"],
        "technical_thresholds": m["technical_thresholds"],
        # 마스터가 손상되면 화면이 먼저 알아야 한다
        "invariant_problems": riskassess.check_master(),
    }


@router.post("/risk/assess")
def risk_assess(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """STEP 1~5 를 돌린다. 저장하지 않는다 — 화면이 입력할 때마다 부르는 경로다."""
    try:
        return riskassess.assess(payload, assessed_at=now_iso())
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(400, f"입력을 해석할 수 없다: {exc}") from exc


@router.get("/risk/drafts")
def risk_drafts() -> dict[str, Any]:
    """저장된 평가 목록. 서비스별로 한 건씩 둔다."""
    saved = _store().read_json(RISK_FILE, default={}) or {}
    out = []
    for key, row in sorted(saved.items()):
        result = row.get("result") or {}
        out.append({
            "service_uuid": key,
            "service_name": row.get("input", {}).get("service_name", ""),
            "saved_at": row.get("saved_at", ""),
            "saved_by": row.get("saved_by", ""),
            "residual_score": result.get("step4_residual_score"),
            "grade": (result.get("final_grade") or {}).get("label", ""),
            "high_impact": (result.get("step1_high_impact") or {}).get("high_impact"),
        })
    return {"drafts": out}


@router.get("/risk/draft/{service_uuid}")
def risk_draft(service_uuid: str) -> dict[str, Any]:
    saved = _store().read_json(RISK_FILE, default={}) or {}
    row = saved.get(service_uuid)
    if not row:
        raise HTTPException(404, f"저장된 평가가 없다: {service_uuid}")
    return row


@router.post("/risk/draft/{service_uuid}")
def risk_save(service_uuid: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """평가를 저장한다. 결과는 저장 시점에 다시 계산해 입력과 함께 남긴다.

    입력만 저장하면 나중에 룰이 바뀌었을 때 그때의 판정을 재현할 수 없고,
    결과만 저장하면 무엇을 눌러서 나온 값인지 알 수 없다. 둘 다 남긴다.
    """
    data = dict(payload.get("input") or payload)
    data["service_uuid"] = service_uuid
    by = str(payload.get("by", "")).strip()
    if not by:
        raise HTTPException(400, "저장자(by)가 필요하다")
    result = riskassess.assess(data, assessed_at=now_iso())

    store = _store()
    saved = store.read_json(RISK_FILE, default={}) or {}
    saved[service_uuid] = {
        "input": data,
        "result": result,
        "saved_at": now_iso(),
        "saved_by": by,
    }
    store.write_json(RISK_FILE, saved)
    return saved[service_uuid]


@router.delete("/risk/draft/{service_uuid}")
def risk_delete(service_uuid: str) -> dict[str, Any]:
    store = _store()
    saved = store.read_json(RISK_FILE, default={}) or {}
    removed = saved.pop(service_uuid, None) is not None
    if removed:
        store.write_json(RISK_FILE, saved)
    return {"removed": removed}


@router.get("/risk/advisors")
def risk_advisors() -> dict[str, Any]:
    """조언을 줄 수 있는 공급자와 그 위치(사내/외부).

    화면이 "지금 누가 답할 수 있는가" 와 "외부로 나가는가" 를 먼저 보여 줘야
    사용자가 외부 허용을 켤지 판단할 수 있다.
    """
    if _cfg is None:
        raise HTTPException(503, "설정이 없다")
    out = []
    for name in _cfg.providers:
        if name == "template":
            continue
        pcfg = _cfg.with_provider(name)
        opts = pcfg.llm_options
        out.append({
            "id": name,
            "model": opts.get("model", ""),
            "local": name in advisor.LOCAL_PROVIDERS,
            "ready": check_provider(name, opts).to_dict(),
        })
    return {
        "advisors": out,
        "local_first": [n for n in _cfg.providers if n in advisor.LOCAL_PROVIDERS],
    }


@router.post("/risk/advise")
def risk_advise(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """위험 항목 하나에 대한 sLM 조언. **판정하지 않는다.**

    코드 분석 사실(program_ids 로 지정)을 함께 넣어 준다. 모델이 지어내지
    못하도록 프롬프트에 "여기 없는 것은 지어내지 마라" 를 박아 두었다.
    """
    try:
        item_no = int(payload.get("item_no"))
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, "item_no 가 필요하다") from exc

    stage = str(payload.get("stage", "identify"))
    if stage not in ("identify", "mitigate"):
        raise HTTPException(400, "stage 는 identify 또는 mitigate 여야 한다")

    facts = _code_facts(
        [str(x) for x in (payload.get("program_ids") or [])],
        project=payload.get("project"),
    )
    result = advisor.advise(
        _cfg,
        item_no=item_no,
        stage=stage,
        service=str(payload.get("service", "")),
        profile=dict(payload.get("profile") or {}),
        facts=facts,
        identified_note=str(payload.get("note", "")),
        allow_external=bool(payload.get("allow_external")),
    )
    return {**result.to_dict(), "facts": facts}


def _code_facts(program_ids: list[str], *, project: str | None = None) -> dict[str, Any]:
    """정적 분석이 확인한 사실만 모은다 (derivation=collected).

    조언 프롬프트의 근거가 된다. 여기 없는 것을 모델이 말하면 그건 지어낸 것이다.
    """
    if not program_ids:
        return {}
    try:
        from ..indexer import load_index
        from ..server.app import registry  # 지연 import — 순환을 피한다

        proj = registry.get(project)
        idx = load_index(registry.config_for(proj), with_source=False)
    except Exception:  # noqa: BLE001 — 인덱스가 없으면 코드 근거 없이 간다
        return {}

    wanted = set(program_ids)
    programs = [p for p in idx.programs if p.id in wanted]
    if not programs:
        return {}

    tables: set[str] = set()
    urls: list[str] = []
    layers: set[str] = set()
    crud: dict[str, set[str]] = {}
    for p in programs:
        tables.update(p.tables)
        urls.extend(p.urls)
        if p.layer:
            layers.add(p.layer)
        for sid in p.sql_ids:
            st = idx.statements.get(sid)
            if not st:
                continue
            for table, op in st.crud:
                crud.setdefault(table, set()).add(op)
    externals, metrics = _call_signals(idx, programs)
    return {
        "programs": [p.name for p in programs],
        "program_ids": [p.id for p in programs],
        "urls": sorted(set(urls)),
        "tables": sorted(tables),
        "layers": sorted(layers),
        "crud": {t: sorted(ops) for t, ops in sorted(crud.items())},
        # 외부 호출·성능 측정은 테이블만 봐서는 안 나온다. 클래스의 import·필드·
        # 호출에서 이름으로 찾는다 — 이름이라 확정이 아니라 후보다.
        "externals": externals,
        "metrics": metrics,
    }


def _call_signals(idx: Any, programs: list[Any]) -> tuple[list[str], list[str]]:
    """외부 호출 지점과 성능·드리프트 측정 흔적. 둘 다 '이름으로 보이는 것'이다."""
    ext_pats = [p.lower() for p in codehints.rules()["external_calls"]]
    met_pats = [p.lower() for p in codehints.rules()["metric_markers"]]
    externals: set[str] = set()
    metrics: set[str] = set()

    for program in programs:
        for fqn in program.classes:
            cls = idx.classes.get(fqn)
            if cls is None:
                continue
            names = list(cls.imports) + [t for t, _ in cls.fields] + [cls.name]
            for method in cls.methods:
                names.append(method.name)
                names.extend(recv for recv, _ in method.calls)
                names.extend(m for _, m in method.calls)
            for name in names:
                low = str(name).lower()
                for pat in ext_pats:
                    if pat in low:
                        externals.add(pat)
                for pat in met_pats:
                    if pat in low:
                        metrics.add(pat)
    return sorted(externals), sorted(metrics)


def _pick(props: dict[str, Any], key: str, lang: str | None) -> str:
    """표시 이름을 언어에 맞춰 고른다.

    데이터는 한국어를 원본으로 두고 `<key>_en` 을 별칭으로 갖는다. 별칭이 없으면
    원본을 그대로 쓴다 — 번역이 없다고 화면이 비면 안 된다.
    """
    if i18n.normalize(lang) == "en":
        alias = props.get(f"{key}_en")
        if alias:
            return str(alias)
    return str(props.get(key, ""))


def _prior(g: Any) -> dict[str, dict[str, str]]:
    prior: dict[str, dict[str, str]] = {}
    for node in sorted(g.of_type("Assessment"),
                       key=lambda n: str(n["props"].get("assessed_at", ""))):
        props = node["props"]
        svc, code = props.get("service_uuid"), props.get("control_code")
        if svc and code:
            prior.setdefault(str(svc), {})[str(code)] = str(props.get("verdict"))
    return prior
