"""문서 지식베이스 API (`/api/kb/…`).

읽기와 쓰기가 나뉘어 있다는 점이 중요하다.

* `POST /analyze` 는 **적재하지 않는다.** 파싱·분류·게이트·온톨로지까지만 하고
  결과를 돌려준다. 사람이 업종을 확정하는 자리를 남기기 위한 것이다.
* `POST /ingest` 만이 저장소를 움직인다. 게이트를 우회하는 인자는 없다 —
  ``upload_allowed`` 가 False 거나 업종이 미확정이면 분석 결과만 돌려주고 만다.

`llmwiki/server/compliance.py` 와 같은 `bind(cfg)` 방식으로 붙는다. SPA 폴백보다
**먼저** 등록해야 한다 (라우트는 선언 순서대로 매칭된다).
"""

from __future__ import annotations

import os
import shutil
import tempfile
import urllib.parse
from typing import Any

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response

from ..config import Config
from ..i18n import normalize
from ..kb import classify, gate, ingest as kb_ingest, ontology, parse, sources, taxonomy
from ..kb.store import Store

router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
#: 받아들이는 확장자. 목록의 원본은 `kb/sources.py` 하나뿐이다 — 화면·API·파서가
#: 각자 목록을 들면 어딘가는 반드시 어긋난다.
ALLOWED_SUFFIXES = set(sources.SUFFIX_KIND)

# 예전 이름. 다른 모듈이 참조하고 있을 수 있어 남겨 둔다.
MAX_PDF_BYTES = MAX_UPLOAD_BYTES

_cfg: Config | None = None


def bind(cfg: Config) -> APIRouter:
    global _cfg
    _cfg = cfg
    return router


def _config() -> Config:
    if _cfg is None:  # pragma: no cover - 서버가 항상 bind 한다
        raise HTTPException(503, "지식베이스 설정이 없다")
    return _cfg


def _store() -> Store:
    return Store(_config().kb_dir)


def _destination() -> gate.Destination:
    """서버 설정이 정한 기본 목적지 (config.yaml 의 kb.destination → llm.provider)."""
    return gate.destination_for(_config().kb_destination)


def _requested_destination(provider: str | None) -> tuple[str, gate.Destination]:
    """화면이 고른 공급자를 목적지로 바꾼다. 고르지 않았으면 서버 기본값이다.

    모르는 값은 국외로 **간주하지 않고 거절한다.** `destination_for` 의 보수적
    기본값(국외)은 설정 오타를 막기 위한 것이고, 화면이 보낸 값은 드롭다운의 닫힌
    집합 밖일 이유가 없다 — 조용히 국외로 판정하면 어느 쪽을 고른 결과인지 알 수 없다.
    """
    if not provider:
        return _default_provider(), _destination()
    if provider not in gate.SELECTABLE_PROVIDERS:
        raise HTTPException(
            400, f"고를 수 없는 공급자다: {provider} "
                 f"({' | '.join(gate.SELECTABLE_PROVIDERS)})")
    return provider, gate.destination_for(provider)


def _default_provider() -> str:
    return _config().kb_destination


def _destination_dict(provider: str, dest: gate.Destination) -> dict[str, Any]:
    return {"provider": provider, "name": dest.name,
            "cross_border": dest.cross_border, "note": dest.note}


def _lang(lang: str | None) -> str:
    return normalize(lang, _config().language if _cfg else "ko")


# --------------------------------------------------------------------------- #
# 상태 · 스키마 · 업종
# --------------------------------------------------------------------------- #
@router.get("/health")
def health() -> dict[str, Any]:
    dest = _destination()
    store = _store()
    return {
        "status": "ok",
        "ontology": ontology.KB_ONTOLOGY_VERSION,
        "channels": list(parse.CHANNELS),
        "sectors": len(taxonomy.SECTOR_CODES),
        "parser_ready": _parser_ready(),
        "destination": _destination_dict(_default_provider(), dest),
        # 화면 드롭다운의 유일한 출처. 화면이 목록을 따로 들고 있으면 공급자가
        # 늘었을 때 한쪽만 갱신되어 판정과 표시가 어긋난다.
        "destinations": gate.selectable_destinations(),
        "store": {"root": str(store.root), **store.stats()},
    }


def _parser_ready() -> dict[str, Any]:
    """형식별 준비 상태. 화면이 **업로드하기 전에** 알아야 한다 — 올리고 나서
    '아무것도 없음'을 보면 파일이 빈 것인지 도구가 없는 것인지 알 수 없다.

    `ok` 는 '무엇 하나라도 읽을 수 있는가' 다. 이미지 OCR 만 빠진 상태는 정상적으로
    있을 수 있으므로 전체를 실패로 칠하지 않는다.
    """
    formats = sources.readiness()
    return {
        "ok": bool(formats["pdf"]["ok"] or formats["sheet"]["ok"]),
        "reason": "" if formats["pdf"]["ok"] else formats["pdf"]["reason"],
        "hint": "" if formats["pdf"]["ok"] else formats["pdf"]["hint"],
        "formats": formats,
    }


@router.get("/schema")
def schema() -> dict[str, Any]:
    return {
        **ontology.schema_dict(),
        "severities": list(gate.SEVERITIES),
        "verdict_labels": gate.VERDICT_LABELS,
        "classify": {
            "margin_threshold": classify.MARGIN_THRESHOLD,
            "min_score": classify.MIN_SCORE,
            "methods": list(classify.METHODS),
        },
    }


@router.get("/sectors")
def sectors(lang: str | None = Query(None)) -> dict[str, Any]:
    """업종 닫힌 집합. 화면 드롭다운의 유일한 출처."""
    return {"sectors": taxonomy.as_dict(_lang(lang)), "count": len(taxonomy.SECTOR_CODES)}


@router.get("/sectors/{code}")
def sector(code: str, lang: str | None = Query(None)) -> dict[str, Any]:
    lg = _lang(lang)
    try:
        p = taxonomy.get(code)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "code": p.code,
        "name": taxonomy.sector_name(p.code, lg),
        "ksic": p.ksic,
        "unit_basis": p.unit_basis_en if lg == "en" else p.unit_basis,
        "notes": p.notes,
        "energy_sources": list(p.energy_sources),
        "key_equipment": list(p.key_equipment),
        "required_metrics": [
            {"code": m, "label": taxonomy.metric_label(m, lg)} for m in p.required_metrics
        ],
        "partition": taxonomy.partition(p.code),
    }


# --------------------------------------------------------------------------- #
# 게이트 (텍스트 단위) — 문서를 올리지 않고도 규칙을 확인할 수 있게 둔다
# --------------------------------------------------------------------------- #
@router.post("/gate/review")
def gate_review(payload: dict[str, Any] = Body(...),
                lang: str | None = Query(None)) -> dict[str, Any]:
    """텍스트에 대한 규제 검토. 규칙 기반이라 LLM 호출이 없다."""
    text = str(payload.get("text", ""))
    if not text.strip():
        raise HTTPException(400, "검토할 텍스트가 필요하다")
    provider = payload.get("destination_provider")
    dest = gate.destination_for(provider) if provider else _destination()
    return gate.review(
        text,
        destination=dest,
        masking_enabled=bool(payload.get("masking_enabled")),
        lang=_lang(lang),
        has_output_labeling=bool(payload.get("has_output_labeling")),
        has_prior_notice=bool(payload.get("has_prior_notice")),
    )


@router.post("/gate/mask")
def gate_mask(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """비식별 처리 + 검산. 잔존 항목이 있으면 clean=false 로 알린다."""
    text = str(payload.get("text", ""))
    if not text.strip():
        raise HTTPException(400, "비식별 처리할 텍스트가 필요하다")
    return gate.verify_masking(text)


# --------------------------------------------------------------------------- #
# 문서 분석 · 적재
# --------------------------------------------------------------------------- #
def _save_upload(filename: str, content: bytes) -> str:
    suffix = os.path.splitext((filename or "").lower())[1]
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            400,
            f"지원하지 않는 형식이다: {suffix or '확장자 없음'} "
            f"(가능: {', '.join(sorted(ALLOWED_SUFFIXES))})")
    if not content:
        raise HTTPException(400, "빈 파일이다")
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(400, f"파일이 너무 크다 (최대 {MAX_PDF_BYTES // 1024 // 1024}MB)")
    # 확장자를 그대로 살린다. `.pdf` 로 고정하면 엑셀·이미지가 PDF 파서로 들어간다.
    # 원래 파일명을 살린다. mkstemp 이름(`tmp9zzj.pdf`)을 쓰면 그 이름이 그대로
    # 문서 해시 옆에 남아, 나중에 위키의 `source_span` 이 존재하지 않는 파일을 가리킨다.
    safe = os.path.basename(filename or f"upload{suffix}").replace("/", "_")
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, safe or f"upload{suffix}")
    with open(path, "wb") as f:
        f.write(content)
    return path


def _check_sector(sector: str | None) -> str | None:
    if not sector:
        return None
    try:
        taxonomy.get(sector)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return sector


def _analyze(path: str, sector: str | None, *, build_excel: bool, lang: str,
             destination: gate.Destination):
    try:
        return kb_ingest.analyze(
            path,
            sector_override=sector,
            destination=destination,
            build_excel=build_excel,
            out_dir=tempfile.gettempdir(),
            lang=lang,
            # 이 화면은 사전 고지(kbPriorNotice)와 생성물 표시(kbOutputMark)를 상시
            # 노출한다. 기본값(False)을 그대로 쓰면 지켜지고 있는 의무를 위반으로
            # 보고하게 된다. 문구를 화면에서 빼면 이 두 줄도 함께 내려야 한다.
            has_prior_notice=True,
            has_output_labeling=True,
        )
    except parse.ParseError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    sector: str | None = Form(None),
    build_excel: bool = Form(True),
    lang: str | None = Form(None),
    destination_provider: str | None = Form(None),
) -> dict[str, Any]:
    """문서 1건을 4채널로 분해하고 분류·게이트·온톨로지까지 만든다.

    **적재하지 않는다.** 사람이 결과를 확인하고 업종을 확정한 뒤 `/ingest` 로 넘어간다.

    ``destination_provider`` 는 이 문서를 어느 LLM 으로 보낼 것인지다. 국외 이전
    해당성(개인정보보호법 제28조의8)이 여기서 갈리므로, 판정 결과와 함께
    무엇을 기준으로 판정했는지를 ``destination`` 으로 돌려준다.
    """
    content = await file.read()
    path = _save_upload(file.filename or "", content)
    provider, dest = _requested_destination(destination_provider)
    try:
        res = _analyze(path, _check_sector(sector), build_excel=build_excel,
                       lang=_lang(lang), destination=dest)
        out = res.to_dict()
        out["graph"] = res.graph
        # 채널별 내용은 저장소에 복제하지 않고 응답에만 싣는다 (`to_dict()` 가 뺀다).
        out["preview"] = res.preview
        out["destination"] = _destination_dict(provider, dest)
        return out
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    sector: str | None = Form(None),
    mask: bool = Form(True),
    lang: str | None = Form(None),
    destination_provider: str | None = Form(None),
) -> dict[str, Any]:
    """분석 → 게이트 → 업종 구획 적재.

    게이트를 우회하는 인자는 없다. ``mask=False`` 로 비식별을 꺼도 개인정보가 남아
    있으면 저장소가 거부하므로, 결국 비식별을 거친 것만 들어간다.
    """
    content = await file.read()
    path = _save_upload(file.filename or "", content)
    provider, dest = _requested_destination(destination_provider)
    dest_dict = _destination_dict(provider, dest)
    try:
        res = _analyze(path, _check_sector(sector), build_excel=True,
                       lang=_lang(lang), destination=dest)
        out = res.to_dict()
        out["preview"] = res.preview
        out["destination"] = dest_dict
        out["stored"] = _store().ingest(res, mask=mask, destination=dest_dict)
        return out
    finally:
        shutil.rmtree(os.path.dirname(path), ignore_errors=True)


# --------------------------------------------------------------------------- #
# 적재된 문서
# --------------------------------------------------------------------------- #
@router.get("/documents")
def documents(sector: str | None = Query(None)) -> dict[str, Any]:
    # 집계는 `stats` 아래에 둔다. 펼쳐서 합치면 stats 의 documents(건수)가 목록을
    # 덮어써 화면이 숫자를 순회하려 든다.
    store = _store()
    return {"documents": store.documents(_check_sector(sector)), "stats": store.stats()}


@router.get("/documents/{doc_hash}")
def document(doc_hash: str) -> dict[str, Any]:
    store = _store()
    rec = store.record(doc_hash)
    if rec is None:
        raise HTTPException(404, f"적재된 문서를 찾을 수 없다: {doc_hash}")
    return {
        **rec,
        "analysis": store.analysis(doc_hash),
        "graph_stats": (store.graph(doc_hash) or {}).get("stats"),
        "has_excel": store.excel(doc_hash) is not None,
    }


@router.get("/documents/{doc_hash}/graph")
def document_graph(doc_hash: str) -> dict[str, Any]:
    graph = _store().graph(doc_hash)
    if graph is None:
        raise HTTPException(404, f"그래프가 없다: {doc_hash}")
    return graph


@router.get("/documents/{doc_hash}/graph.ttl")
def document_turtle(doc_hash: str) -> Response:
    ttl = _store().turtle(doc_hash)
    if ttl is None:
        raise HTTPException(404, f"TTL 이 없다: {doc_hash}")
    return Response(content=ttl, media_type="text/turtle")


@router.get("/documents/{doc_hash}/tables.xlsx")
def document_excel(doc_hash: str) -> FileResponse:
    path = _store().excel(doc_hash)
    if path is None:
        raise HTTPException(404, f"엑셀 채널이 없다: {doc_hash}")
    quoted = urllib.parse.quote(f"{doc_hash}_tables.xlsx")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@router.get("/search")
def search(q: str = Query(..., min_length=1), sector: str | None = Query(None),
           channel: str | None = Query(None), limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    """적재된 채널을 검색한다. 업종·채널 필터는 코드가 실제로 건다."""
    if channel and channel not in parse.CHANNELS:
        raise HTTPException(400, f"채널은 {parse.CHANNELS} 중 하나여야 한다")
    hits = _store().search(q, sector=_check_sector(sector), channel=channel, limit=limit)
    return {"query": q, "sector": sector, "channel": channel, "results": hits}


# --------------------------------------------------------------------------- #
# 그래프 도구
# --------------------------------------------------------------------------- #
@router.post("/graph/ttl")
def graph_to_ttl(graph: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """온톨로지 그래프를 TTL 로. Fuseki 적재/SPARQL 질의로 이어진다."""
    if "nodes" not in graph:
        raise HTTPException(400, "nodes 가 없는 그래프다")
    ttl = ontology.to_turtle(graph)
    return {"ttl": ttl, "lines": len(ttl.splitlines())}


@router.post("/graph/validate")
def graph_validate(graph: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if "nodes" not in graph:
        raise HTTPException(400, "nodes 가 없는 그래프다")
    result = ontology.validate_graph(graph)
    return {
        "ok": result.ok,
        "errors": len(result.errors),
        "warnings": len(result.warnings),
        "issues": [i.__dict__ for i in result.issues],
    }
