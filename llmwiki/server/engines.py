"""엔진 레이어 API (`/api/engines`).

이 제품에는 화면이 두 갈래(소스 분석 · 보고서 지식화)지만 **엔진은 하나**다.
sLM·Grok·검색·규제 판정은 두 솔루션이 같은 것을 나눠 쓴다. 그런데 화면마다
따로 상태를 보여 주면 사용자는 그것들을 각 화면의 기능으로 오해하고, 한쪽에서
Grok 키가 빠졌을 때 다른 쪽도 함께 멈춘다는 사실을 모른다.

그래서 엔진은 **메뉴가 아니라 레이어**로 만든다. 이 엔드포인트 하나가 네 엔진의
상태를 모아 주고, 화면 어디서든 같은 값을 본다.

| 엔진 | 무엇 | 두 솔루션에서 하는 일 |
|---|---|---|
| `sllm` | 사내 Ollama | 사외 반출 금지 문서의 유일한 경로 (ACL 판정 결과) |
| `grok` | xAI API | 문서 간 추론 · 서술 초안 · 명세서 생성 |
| `rag` | 하이브리드 검색 | 채널 검색(kb) + 위키 검색(BM25 ⊕ n-그램 RRF) |
| `aigov` | 규제 판정 | 적재 게이트(개인정보·AI기본법) + 근거기반 준수 판정 |

**상태 조회에 네트워크가 붙는다.** Ollama·xAI 를 실제로 찔러 보기 때문이다.
화면 전환마다 왕복하면 눈에 띄게 굼떠지므로 짧게 캐시한다 — 실패도 캐시한다
(연결이 끊긴 동안 매 요청이 5초씩 걸리면 화면 전체가 느려진다). `?refresh=1` 로
즉시 다시 확인할 수 있다.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Query

from ..compliance.store import Store as ComplianceStore
from ..config import Config
from ..ediag import retrieval, route
from ..ediag.store import WikiStore
from ..kb import gate, taxonomy
from ..kb.store import Store as KbStore
from ..llm import preflight

router = APIRouter(prefix="/api/engines", tags=["engines"])

#: 상태 캐시 수명(초). 사람이 키를 고치고 확인하는 시간 감각에 맞춘다.
TTL = 30.0

#: 엔진 코드의 닫힌 집합. 화면의 표시 순서이기도 하다.
ENGINE_CODES: tuple[str, ...] = ("sllm", "grok", "rag", "aigov")

#: 상태 어휘. `idle` 은 '고장이 아니라 아직 쓸 자료가 없음' 이다 — 이 둘을 같은
#: 빨간불로 보여 주면 사용자가 멀쩡한 시스템을 고치려 든다.
STATUSES: tuple[str, ...] = ("ok", "idle", "unavailable")

_cfg: Config | None = None
_cache: dict[str, Any] = {}


def bind(cfg: Config) -> APIRouter:
    global _cfg
    _cfg = cfg
    return router


def _config() -> Config:
    if _cfg is None:  # pragma: no cover - 서버가 항상 bind 한다
        raise RuntimeError("엔진 설정이 없다")
    return _cfg


# --------------------------------------------------------------------------- #
# 엔진별 상태
# --------------------------------------------------------------------------- #
def _llm_engine(code: str, provider: str, cfg: Config) -> dict[str, Any]:
    options = cfg.with_provider(provider).llm_options
    ready = preflight.check(provider, options)
    configured = provider in cfg.providers
    return {
        "code": code,
        "provider": provider,
        "status": "ok" if ready.ok else "unavailable",
        "detail": {
            "model": str(options.get("model", "")),
            "base_url": str(options.get("base_url", "")),
            "configured": configured,
            "reason": ready.reason,
            "hint": ready.hint,
        },
    }


def _rag_engine(cfg: Config) -> dict[str, Any]:
    """검색 엔진. 인덱스는 위키에서 매번 다시 만든다 (P1) — 여기서도 그렇게 센다."""
    wiki = WikiStore(cfg.wiki_dir)
    pages = wiki.pages()
    index = retrieval.Index(pages)
    kb = KbStore(cfg.kb_dir)
    kb_stats = kb.stats()
    documents = index.stats()["documents"] + kb_stats.get("documents", 0)
    return {
        "code": "rag",
        "provider": "internal",
        "status": "ok" if documents else "idle",
        "detail": {
            "wiki_pages": index.stats()["documents"],
            "wiki_terms": index.stats()["terms"],
            "kb_documents": kb_stats.get("documents", 0),
            "kb_records": kb_stats.get("records", 0),
            "channels": list(retrieval.CHANNEL_WEIGHTS),
            "rrf_k": retrieval.RRF_K,
            "reason": "" if documents else "적재된 문서가 없다 — 고장이 아니라 자료가 없는 상태다",
            "hint": "" if documents else "위키 관리자에서 진단 보고서를 올리면 인덱스가 생긴다.",
        },
    }


def _aigov_engine(cfg: Config) -> dict[str, Any]:
    """규제 판정 엔진. LLM 을 부르지 않으므로 '연결' 이 아니라 '자료' 로 판정한다."""
    store = ComplianceStore(cfg.compliance_dir)
    try:
        graph = store.approved()
        counts = graph.counts()
        nodes = sum(counts.values()) if counts else 0
    except Exception as exc:  # noqa: BLE001 - 저널이 없거나 깨져도 화면은 떠야 한다
        return {
            "code": "aigov", "provider": "internal", "status": "unavailable",
            "detail": {"reason": f"승인 그래프를 읽을 수 없다: {exc}",
                       "hint": "`llmwiki reg seed` 로 데모 데이터를 만들 수 있다."},
        }
    dest = gate.destination_for(cfg.kb_destination)
    return {
        "code": "aigov",
        "provider": "internal",
        "status": "ok" if nodes else "idle",
        "detail": {
            "ruleset": cfg.ruleset_version,
            "standard": cfg.standard_version,
            "nodes": nodes,
            "journal_records": len(store.read_journal()),
            "sectors": len(taxonomy.SECTOR_CODES),
            "destination": dest.name,
            "cross_border": dest.cross_border,
            "reason": "" if nodes else "승인된 규제 그래프가 없다 — 판정할 대상이 아직 없는 상태다",
            "hint": "" if nodes else "`llmwiki reg seed` 로 데모 데이터를 넣을 수 있다.",
        },
    }


def _collect(cfg: Config) -> dict[str, Any]:
    external = cfg.provider if cfg.provider not in route.INTERNAL_PROVIDERS else "grok"
    engines = [
        _llm_engine("sllm", "ollama", cfg),
        _llm_engine("grok", external if external in ("grok", "claude") else "grok", cfg),
        _rag_engine(cfg),
        _aigov_engine(cfg),
    ]
    return {
        "engines": engines,
        "default_provider": cfg.provider,
        # 어떤 등급이 어디로 가는지 — 화면이 규칙을 다시 구현하지 않도록 서버가 준다.
        "routing": {
            "internal_only_acl": sorted(route.contract.ACL_INTERNAL_ONLY),
            "examples": [
                {"task": task, "acl": acl, **route.decide(task, acl,
                                                          external_provider=external).to_dict()}
                for task, acl in (("wiki_draft", "internal"), ("concept", "internal"),
                                  ("concept", "confidential"), ("report_draft", "confidential"))
            ],
        },
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


@router.get("")
def engines(refresh: bool = Query(False)) -> dict[str, Any]:
    cfg = _config()
    now = time.monotonic()
    if not refresh and _cache and now - _cache.get("at", 0.0) < TTL:
        return {**_cache["payload"], "cached": True}
    payload = _collect(cfg)
    _cache["at"] = now
    _cache["payload"] = payload
    return {**payload, "cached": False}
