"""에너지 진단 위키 API (`/api/wiki/…`).

`llmwiki/server/kb.py` 와 같은 `bind(cfg)` 방식으로 붙고, SPA 폴백보다 **먼저**
등록해야 한다.

읽기와 쓰기가 나뉜다.

* `POST /preview` 는 **저장하지 않는다.** 업로드한 PDF 를 분석하고 페이지 초안까지
  만들어 보여 주기만 한다. 관리자가 사업장 키와 업종을 확정하는 자리다.
* `POST /ingest` 만이 위키를 움직인다. 적재 게이트(`llmwiki/kb/gate.py`)를 통과하지
  못하면 페이지를 만들지 않는다 — 우회 인자는 없다.
* `POST /review/{id}` 는 사람의 서명이다. 서명 없이 상태가 바뀌는 경로는 없다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse

from ..config import Config
from ..ediag import (
    assist as assist_mod,
    build as build_mod,
    calc,
    contract,
    lint as lint_mod,
    retrieval,
    review as review_mod,
    route,
    units as units_mod,
)
from ..ediag.store import WikiStore, write_all
from ..kb import gate, ingest as kb_ingest, parse, sources, taxonomy
from ..kb.store import Store as KbStore

router = APIRouter(prefix="/api/wiki", tags=["energy-diagnosis-wiki"])

MAX_PDF_BYTES = 50 * 1024 * 1024

_cfg: Config | None = None


def bind(cfg: Config) -> APIRouter:
    global _cfg
    _cfg = cfg
    return router


def _config() -> Config:
    if _cfg is None:  # pragma: no cover - 서버가 항상 bind 한다
        raise HTTPException(503, "위키 설정이 없다")
    return _cfg


def _store() -> WikiStore:
    return WikiStore(_config().wiki_dir)


def _acl(value: str | None) -> str:
    """화면이 보낸 등급을 검증한다. 모르는 값은 가장 낮은 등급으로 떨어뜨리지 않고 막는다.

    조용히 낮추면 화면은 '전부 봤다' 고 믿고 사람은 '아무것도 없다' 고 결론 낸다.
    """
    if value is None:
        return "internal"
    if value not in contract.ACL_LEVELS:
        raise HTTPException(400, f"접근 등급은 {contract.ACL_LEVELS} 중 하나여야 한다")
    return value


# --------------------------------------------------------------------------- #
# 상태 · 스키마
# --------------------------------------------------------------------------- #
@router.get("/health")
def health() -> dict[str, Any]:
    cfg = _config()
    store = _store()
    table = units_mod.load()
    res = lint_mod.run(store)
    return {
        "status": "ok",
        "contract": contract.CONTRACT_VERSION,
        "pipeline_version": cfg.wiki_pipeline_version,
        "root": str(store.root),
        "store": store.stats(),
        "units": {"version": table.version, "standard": table.standard,
                  "expiring": [f.to_dict() for f in table.expiring()]},
        "lint": {k: v for k, v in res.to_dict().items() if k != "findings"},
        "parser_ready": _parser_ready(),
        "destination": _destination_info(),
        "review": review_mod.stats(store),
    }


def _parser_ready() -> dict[str, Any]:
    formats = sources.readiness()
    return {
        "ok": bool(formats["pdf"]["ok"] or formats["sheet"]["ok"]),
        "reason": "" if formats["pdf"]["ok"] else formats["pdf"]["reason"],
        "hint": "" if formats["pdf"]["ok"] else formats["pdf"]["hint"],
        "formats": formats,
    }


def _destination_info() -> dict[str, Any]:
    dest = gate.destination_for(_config().kb_destination)
    return {"name": dest.name, "cross_border": dest.cross_border, "note": dest.note}


@router.get("/schema")
def schema() -> dict[str, Any]:
    return {
        **contract.schema_dict(),
        "lint_severities": list(lint_mod.SEVERITIES),
        "review_decisions": list(review_mod.DECISIONS),
        "blocking_codes": sorted(review_mod.BLOCKING_CODES),
        "acl_by_type": build_mod.ACL_BY_TYPE,
        "assist_tasks": list(assist_mod.TASKS),
        "sectors": taxonomy.as_dict("ko"),
    }


@router.get("/units")
def units() -> dict[str, Any]:
    return units_mod.load().to_dict()


@router.get("/routing")
def routing(task: str | None = Query(None), acl: str | None = Query(None)) -> dict[str, Any]:
    if task and acl:
        try:
            return route.decide(task, acl).to_dict()
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from exc
    policy = route.policy()
    policy["matrix"] = [
        {"task": name,
         "internal": route.decide(name, "internal").to_dict(),
         "confidential": route.decide(name, "confidential").to_dict()}
        for name in policy["tasks"]
    ]
    return policy


# --------------------------------------------------------------------------- #
# 생성 (관리자)
# --------------------------------------------------------------------------- #
def _save_upload(filename: str, content: bytes) -> str:
    suffix = os.path.splitext((filename or "").lower())[1]
    if suffix not in sources.SUFFIX_KIND:
        raise HTTPException(
            400,
            f"지원하지 않는 형식이다: {suffix or '확장자 없음'} "
            f"(가능: {', '.join(sorted(sources.SUFFIX_KIND))})")
    if not content:
        raise HTTPException(400, "빈 파일이다")
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(400, f"파일이 너무 크다 (최대 {MAX_PDF_BYTES // 1024 // 1024}MB)")
    # 원래 파일명을 살린다. mkstemp 이름(`tmp9zzj.pdf`)을 쓰면 그 이름이 그대로
    # 문서 해시 옆에 남아, 나중에 위키의 `source_span` 이 존재하지 않는 파일을 가리킨다.
    safe = os.path.basename(filename or f"upload{suffix}").replace("/", "_")
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, safe or f"upload{suffix}")
    with open(path, "wb") as f:
        f.write(content)
    return path


def _run_build(path: str, *, site: str, sector: str | None, owner: str):
    cfg = _config()
    try:
        doc = sources.parse_document(path, extract_images=False)
    except parse.ParseError as exc:
        raise HTTPException(503, str(exc)) from exc
    if sector:
        try:
            taxonomy.get(sector)
        except KeyError as exc:
            raise HTTPException(400, str(exc)) from exc

    analysis = kb_ingest.analyze(
        path, sector_override=sector,
        destination=gate.destination_for(cfg.kb_destination),
        build_excel=False,
        # 이 화면은 사전 고지와 생성물 표시를 상시 노출한다. 문구를 화면에서 빼면
        # 이 두 줄도 함께 내려야 한다 — 안 그러면 지켜지는 의무를 위반으로 보고한다.
        has_prior_notice=True, has_output_labeling=True)

    result = build_mod.build(
        doc,
        options=build_mod.BuildOptions(
            site_key=site, owner=owner or cfg.wiki_owner,
            pipeline_version=cfg.wiki_pipeline_version),
        analysis=analysis.to_dict())
    return doc, analysis, result


def _build_payload(analysis, result) -> dict[str, Any]:
    ex = result.extraction
    return {
        "analysis": analysis.to_dict(),
        "gate_allowed": analysis.upload_allowed,
        "summary": result.summary(),
        "warnings": result.warnings,
        "checks": [c.to_dict() for c in ex.checks],
        "checks_failed": [c.to_dict() for c in ex.failed],
        "pages": [p.summary() for p in result.pages],
    }


@router.post("/preview")
async def preview(
    file: UploadFile = File(...),
    site: str = Form(""),
    sector: str | None = Form(None),
    owner: str = Form(""),
) -> dict[str, Any]:
    """PDF → 페이지 초안. **저장하지 않는다.**

    사업장 키를 사람이 확정하는 자리다. 키가 바뀌면 모든 stable_id 가 바뀌므로,
    저장 전에 눈으로 보는 단계를 반드시 거친다.
    """
    content = await file.read()
    path = _save_upload(file.filename or "", content)
    try:
        _doc, analysis, result = _run_build(path, site=site, sector=sector, owner=owner)
        return {**_build_payload(analysis, result), "stored": False}
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    site: str = Form(""),
    sector: str | None = Form(None),
    owner: str = Form(""),
) -> dict[str, Any]:
    """PDF → 위키 저장. 적재 게이트를 통과하지 못하면 아무것도 쓰지 않는다."""
    content = await file.read()
    path = _save_upload(file.filename or "", content)
    try:
        _doc, analysis, result = _run_build(path, site=site, sector=sector, owner=owner)
        payload = _build_payload(analysis, result)
        if not analysis.upload_allowed:
            return {**payload, "stored": False,
                    "skipped": "적재 게이트가 허용하지 않았다 — 위키를 만들지 않는다"}
        store = _store()
        records = write_all(store, result.pages,
                            actor=owner or _config().wiki_owner,
                            note=f"ingest {file.filename}")
        # 채널 원본을 지식 데이터베이스에도 남긴다. 나중에 이 페이지를 **재분석**할 때
        # 근거가 될 원문이 여기 없으면, 모델은 이미 거칠어진 페이지 본문만 보고
        # 문장을 다듬을 뿐 빠진 맥락을 채우지 못한다.
        channels = _store_channels(analysis)
        res = lint_mod.run(store)
        return {**payload, "stored": True, "records": records, "channels": channels,
                "lint": {k: v for k, v in res.to_dict().items() if k != "findings"}}
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


def _store_channels(analysis) -> dict[str, Any]:
    """분석 결과의 4채널 청크를 kb 저장소에 넣는다. 실패해도 위키 저장은 되돌리지 않는다.

    게이트를 우회하지 않는다 — `Store.ingest` 가 `upload_allowed` 와 마스킹 검산을
    다시 본다. 업종이 미확정이면 넣지 않고 그 사실만 남긴다.
    """
    try:
        return KbStore(_config().kb_dir).ingest(analysis, mask=True)
    except Exception as exc:  # noqa: BLE001 - 위키는 이미 저장됐다. 여기서 실패해도 되돌리지 않는다
        return {"stored": 0, "skipped": f"채널 적재 실패: {exc}"}


def _source_chunks(page) -> list[dict[str, Any]]:
    """페이지가 인용한 원문 문서의 채널 청크. 없으면 빈 목록 — 조용히 다른 문서를
    끌어오지 않는다."""
    docs = [str(span.get("doc", "")) for span in page.source_span if span.get("doc")]
    if not docs:
        return []
    kb = KbStore(_config().kb_dir)
    for record in kb.documents():
        if record.get("filename") in docs:
            return kb.channels(record["doc_hash"])
    return []


# --------------------------------------------------------------------------- #
# 열람
# --------------------------------------------------------------------------- #
@router.get("/pages")
def pages(page_type: str | None = Query(None, alias="type"),
          status: str | None = Query(None),
          acl: str | None = Query(None)) -> dict[str, Any]:
    store = _store()
    rows = store.pages(page_type=page_type, status=status, acl_max=_acl(acl))
    return {
        "pages": [p.summary() for p in rows],
        "stats": store.stats(),
        "types": [{"name": t.name, "ko": t.ko, "en": t.en, "prefix": t.prefix}
                  for t in contract.PAGE_TYPES.values()],
    }


@router.get("/pages/{stable_id}")
def page(stable_id: str, acl: str | None = Query(None)) -> dict[str, Any]:
    store = _store()
    p = store.read(stable_id)
    if p is None:
        raise HTTPException(404, f"페이지가 없다: {stable_id}")
    cap = contract.acl_rank(_acl(acl))
    if contract.acl_rank(p.acl) > cap:
        # 있는데 안 보이는 것과 없는 것을 구분해 준다. 구분하지 않으면 사용자는
        # 지식이 없다고 결론 내리고, 그게 더 나쁘다.
        raise HTTPException(403, f"접근 등급이 부족하다 (페이지 {p.acl})")
    pages_all = store.pages()
    backlinks = [
        q.summary() for q in pages_all
        if q.stable_id in store.backlinks(stable_id, pages_all)
        and contract.acl_rank(q.acl) <= cap
    ]
    res = lint_mod.run(store, pages=pages_all)
    return {
        "page": {**p.summary(), "front_matter": p.front_matter, "body": p.body,
                 "raw": p.dumps()},
        "backlinks": backlinks,
        "findings": [f.to_dict() for f in res.findings if f.page == stable_id],
        "review": review_mod.journal(store, stable_id=stable_id, limit=20),
    }


@router.get("/search")
def search(q: str = Query(..., min_length=1), acl: str | None = Query(None),
           page_type: str | None = Query(None, alias="type"),
           limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    store = _store()
    index = retrieval.Index(store.pages())
    hits = index.search(q, limit=limit, acl_max=_acl(acl), page_type=page_type)
    return {"query": q, "acl": _acl(acl), "index": index.stats(),
            "results": [h.to_dict() for h in hits]}


@router.get("/graph")
def graph(acl: str | None = Query(None)) -> dict[str, Any]:
    store = _store()
    return store.graph(store.pages(acl_max=_acl(acl)))


@router.get("/index.md", response_class=PlainTextResponse)
def catalog() -> str:
    store = _store()
    store.rebuild_index()
    return store.index_path.read_text(encoding="utf-8")


@router.get("/log")
def log(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    return {"log": _store().log(limit=limit)}


# --------------------------------------------------------------------------- #
# 검사 · 검증
# --------------------------------------------------------------------------- #
@router.get("/lint")
def lint() -> dict[str, Any]:
    return lint_mod.run(_store()).to_dict()


@router.get("/review/queue")
def review_queue(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    store = _store()
    items = review_mod.queue(store, limit=limit)
    return {"queue": [i.to_dict() for i in items], "stats": review_mod.stats(store)}


@router.get("/review/journal")
def review_journal(limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    store = _store()
    return {"journal": review_mod.journal(store, limit=limit),
            "stats": review_mod.stats(store)}


@router.post("/review/{stable_id}")
def review_decide(stable_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """검토 결정. 서명(actor)이 없으면 400 이다 — 익명 확정 경로를 두지 않는다."""
    store = _store()
    try:
        return review_mod.decide(
            store, stable_id,
            str(payload.get("decision", "approve")),
            actor=str(payload.get("actor", "")),
            note=str(payload.get("note", "")),
            acknowledge_unverified=bool(payload.get("acknowledge_unverified")))
    except review_mod.ReviewError as exc:
        raise HTTPException(400, str(exc)) from exc


# --------------------------------------------------------------------------- #
# 서술 초안 제안 — LLM 이 말만 쓰고 수는 못 쓴다
# --------------------------------------------------------------------------- #
@router.post("/assist")
def assist(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """개선안 카드의 `[검토 필요]` 자리에 넣을 **서술** 초안을 제안한다.

    * 페이지를 고치지 않는다. 제안만 돌려주고 반영은 사람이 한다.
    * `confidential` 이상은 외부 모델로 나가지 않는다 (P5). 판정은 `route.decide()`.
    * `provider` 로 사내/외부를 고른다. 고르지 않으면 사내가 기본이고, 외부를 고른
      것 자체가 사외 전송 동의다. 등급이 이기면 고른 것과 다른 경로로 가는데,
      그 사실을 응답의 `requested`·`overridden` 으로 알린다.
    * 답변에 원문에 없는 수가 있으면 그 수를 함께 돌려준다 (P2 는 출력에서 검사한다).
    """
    store = _store()
    stable_id = str(payload.get("stable_id", ""))
    page = store.read(stable_id)
    if page is None:
        raise HTTPException(404, f"페이지가 없다: {stable_id}")
    try:
        suggestion = assist_mod.suggest(
            page, cfg=_config(), task=str(payload.get("task", "concept")),
            provider=str(payload.get("provider", "")),
            allow_external=bool(payload.get("allow_external")),
            context=str(payload.get("context", "")))
    except assist_mod.AssistError as exc:
        raise HTTPException(400, str(exc)) from exc
    return suggestion.to_dict()


@router.post("/reanalyze")
def reanalyze(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """페이지 하나를 **원문 발췌를 근거로** 다시 쓴다. 저장하지 않는다.

    규칙이 만든 페이지는 문장이 거칠고 맥락이 빠져 있다. 재분석은 그 페이지가 인용한
    쪽의 원문을 함께 넣어 서술을 다시 쓰게 한다 — 수치와 표는 그대로 두고.

    반영은 `POST /pages/{id}/apply` 가 따로 한다. 자동 반영하지 않는 이유는, 검토가
    끝난 페이지가 조용히 바뀌면 그 서명이 무엇을 보증하는지 알 수 없기 때문이다.
    """
    store = _store()
    stable_id = str(payload.get("stable_id", ""))
    page = store.read(stable_id)
    if page is None:
        raise HTTPException(404, f"페이지가 없다: {stable_id}")
    chunks = _source_chunks(page)
    try:
        suggestion = assist_mod.reanalyze(
            page, cfg=_config(), chunks=chunks, provider=str(payload.get("provider", "")))
    except assist_mod.AssistError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        **suggestion.to_dict(),
        "current_body": page.body,
        "context_chars": len(assist_mod.source_excerpt(page, chunks)),
        "context_pages": sorted({p for s in page.source_span for p in (s.get("pages") or [])}),
    }


@router.post("/pages/{stable_id}/apply")
def apply_body(stable_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """재분석 결과를 페이지에 반영한다. 사람의 서명이 있어야 한다.

    반영하면 버전이 오르고 상태가 `draft` 로 돌아간다 — 바뀐 내용은 다시 검토받아야
    한다. 원문에 없는 수가 들어 있으면 막는다: 서술을 고치라고 부른 모델이 수치를
    바꿔 놓는 것이 이 기능의 가장 큰 위험이다.
    """
    store = _store()
    page = store.read(stable_id)
    if page is None:
        raise HTTPException(404, f"페이지가 없다: {stable_id}")

    actor = str(payload.get("actor", "")).strip()
    if not actor:
        raise HTTPException(400, "서명 없이 반영할 수 없다 — 검토자를 지정한다")
    body = str(payload.get("body", "")).strip()
    if not body:
        raise HTTPException(400, "반영할 본문이 비어 있다")

    known = "\n".join([page.body, assist_mod.source_excerpt(page, _source_chunks(page))])
    invented = assist_mod.check_numbers(body, known)
    if invented and not bool(payload.get("acknowledge_numbers")):
        raise HTTPException(
            400,
            "원문에 없는 수가 들어 있다: " + ", ".join(invented[:8])
            + " — 서술만 고치라고 부른 모델이 수치를 바꿨다. 확인하고 지운 뒤 반영한다.")
    ok, missing = assist_mod.structure_kept(page.body, body)
    if not ok and not bool(payload.get("acknowledge_structure")):
        raise HTTPException(
            400,
            "절 구조가 유지되지 않았다"
            + (f" (사라진 제목: {', '.join(missing[:3])})" if missing else "")
            + " — 그대로 반영하면 페이지 형식이 무너진다.")

    page.body = body
    record = store.write(page, actor=actor,
                         note=payload.get("note") or "재분석 결과 반영")
    store.rebuild_index()
    saved = store.read(stable_id)
    return {
        **record,
        "invented_numbers": invented,
        "structure_kept": ok,
        "page": saved.summary() if saved else None,
    }


# --------------------------------------------------------------------------- #
# 계산기 — 위키에 적히는 값과 같은 함수를 쓴다
# --------------------------------------------------------------------------- #
@router.post("/calc")
def calculate(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """수치 계산·검산. LLM 을 부르지 않는다 (P2)."""
    table = units_mod.load()
    out: dict[str, Any] = {"units_version": table.version}
    try:
        if payload.get("kw") and payload.get("hours"):
            kwh = calc.annual_kwh(float(payload["kw"]), float(payload["hours"]),
                                  float(payload.get("load_pct", 100)) / 100.0,
                                  int(payload.get("count", 1)))
            out["electricity"] = {
                "annual_kwh": round(kwh, 2),
                "toe": round(calc.toe_from_kwh(kwh, table), 4),
                "tco2eq": round(calc.tco2eq_from_kwh(kwh, table), 4),
                "cost_kwon": round(calc.elec_cost_kwon(kwh, table), 2),
            }
        if payload.get("fuel_kg_h") and payload.get("hours_per_day"):
            kg = calc.annual_fuel_kg(float(payload["fuel_kg_h"]),
                                     float(payload["hours_per_day"]),
                                     float(payload.get("days", 300)),
                                     float(payload.get("load_pct", 100)) / 100.0)
            out["fuel"] = {
                "annual_kg": round(kg, 2),
                "toe": round(calc.toe_from_lpg_kg(kg, table), 4),
                "tco2eq": round(calc.tco2eq_from_lpg_kg(kg, table), 4),
                "cost_kwon": round(calc.lpg_cost_kwon(kg, table), 2),
            }
        if payload.get("investment_kwon") and payload.get("saving_kwon"):
            years = calc.payback_years(float(payload["investment_kwon"]),
                                       float(payload["saving_kwon"]))
            out["payback_years"] = None if years == float("inf") else round(years, 3)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, f"입력을 숫자로 읽을 수 없다: {exc}") from exc
    if len(out) == 1:
        raise HTTPException(400, "계산할 입력이 없다")
    return out
