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

from ..compliance import advise as advisor
from ..compliance import analysis, changeset as cs, riskassess, rules, verify
from ..compliance import i18n
from ..compliance.ontology import node_id, schema_dict
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
    return {
        "programs": [p.name for p in programs],
        "program_ids": [p.id for p in programs],
        "urls": sorted(set(urls)),
        "tables": sorted(tables),
        "layers": sorted(layers),
        "crud": {t: sorted(ops) for t, ops in sorted(crud.items())},
    }


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
