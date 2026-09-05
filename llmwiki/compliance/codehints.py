"""정적 분석 사실 → 위험평가 입력 **후보**. 결정론적 룰이고 LLM 이 없다.

이 파일이 지키는 선은 하나다 — **제안은 판정이 아니다.**

코드가 `TB_CUST` 를 읽는다는 것은 "개인정보를 처리한다" 는 신호지
"개인정보를 부적절하게 처리한다" 는 판정이 아니다. 그래서 여기서 나오는 것은
전부 `candidate` 이고, 화면은 체크박스를 미리 켜지 않는다. Yes/No 를 누르는 것은
사람이고, 그 순간 그 값의 derivation 이 `human` 이 된다.

과장하지 않기 위해 답할 수 없는 것도 함께 돌려준다(`unanswerable`). 고영향 판단과
산출물 특성·의사결정 영향도는 코드에 없다. 화면이 이것을 명시해야 감리에서
"무엇을 자동으로 채웠나" 에 답할 수 있다.

패턴은 `data/code_hints.yaml` 이 단일 원본이다 — 명명규칙은 현장마다 달라서
코드가 아니라 데이터로 두어야 고칠 수 있다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

HINTS_PATH = Path(__file__).parent / "data" / "code_hints.yaml"

#: 제안의 신뢰도. 화면이 색이 아니라 형태로도 구분한다.
CANDIDATE = "candidate"


@lru_cache(maxsize=1)
def rules() -> dict[str, Any]:
    with HINTS_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _hit(text: str, patterns: list[str]) -> bool:
    low = text.lower()
    return any(p.lower() in low for p in patterns)


def _matching(values: list[str], patterns: list[str]) -> list[str]:
    return [v for v in values if _hit(str(v), patterns)]


def _ev(kind: str, ident: str, label: str = "") -> dict[str, str]:
    """근거 한 조각. 화면은 kind 로 링크 대상을 정한다 (program → /p/<id>)."""
    return {"kind": kind, "id": str(ident), "label": str(label or ident)}


# --------------------------------------------------------------------------- #
# 프로파일 2축
# --------------------------------------------------------------------------- #
def _user_scope(facts: dict[str, Any]) -> dict[str, Any] | None:
    layers = [str(x) for x in facts.get("layers", [])]
    urls = [str(x) for x in facts.get("urls", [])]
    cands: list[dict[str, Any]] = []
    for spec in rules()["user_scope"]:
        hit_layers = _matching(layers, spec.get("layers", []))
        hit_urls = _matching(urls, spec.get("urls", []))
        if not hit_layers and not hit_urls:
            continue
        evidence = ([_ev("layer", x) for x in hit_layers]
                    + [_ev("url", x) for x in hit_urls[:6]])
        cand = {
            "axis": "user_scope",
            "value": spec["value"],
            "confidence": CANDIDATE,
            "because": ("계층 " + ", ".join(hit_layers) if hit_layers else "")
                       + (" · " if hit_layers and hit_urls else "")
                       + ("URL " + ", ".join(hit_urls[:3]) if hit_urls else ""),
            "evidence": evidence,
            "score": len(hit_layers) * 2 + len(hit_urls),
        }
        cands.append(cand)

    if not cands:
        return None
    cands.sort(key=lambda c: c["score"], reverse=True)
    # 채널계와 기관계가 섞여 있으면 더 많이 걸린 쪽을 낸다. 동점이면 제안하지
    # 않는다 — 애매한 것을 채워 두면 사람이 검토하지 않고 넘어간다.
    if len(cands) > 1 and cands[0]["score"] == cands[1]["score"]:
        return None
    out = dict(cands[0])
    out.pop("score", None)
    return out


def _sensitivity(facts: dict[str, Any]) -> dict[str, Any] | None:
    tables = [str(t) for t in facts.get("tables", [])]
    if not tables:
        return None
    for spec in rules()["data_sensitivity"]:
        pats = spec.get("tables", [])
        if not pats:
            continue
        hit = _matching(tables, pats)
        if hit:
            return {
                "axis": "data_sensitivity",
                "value": spec["value"],
                "confidence": CANDIDATE,
                "because": "접근 테이블 " + ", ".join(hit[:4]),
                "evidence": [_ev("table", t) for t in hit[:8]],
            }
    fallback = rules()["data_sensitivity"][-1]["value"]
    return {
        "axis": "data_sensitivity",
        "value": fallback,
        "confidence": CANDIDATE,
        "because": f"접근 테이블 {len(tables)} 개 중 개인정보로 보이는 이름이 없다",
        "evidence": [_ev("table", t) for t in tables[:8]],
    }


# --------------------------------------------------------------------------- #
# 위험 항목
# --------------------------------------------------------------------------- #
def _signals(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """규칙이 참조하는 조건들을 한 번에 계산한다."""
    spec = {s["value"]: s for s in rules()["data_sensitivity"]}
    personal_pats = spec["개인정보"]["tables"]
    sensitive_pats = spec["민감·신용정보"]["tables"]

    tables = [str(t) for t in facts.get("tables", [])]
    crud: dict[str, list[str]] = {str(k): list(v) for k, v in (facts.get("crud") or {}).items()}
    personal = _matching(tables, personal_pats + sensitive_pats)
    sensitive = _matching(tables, sensitive_pats)
    written = [t for t in personal if {"C", "U"} & set(crud.get(t, []))]
    read = [t for t in personal if "R" in crud.get(t, [])]
    scope = _user_scope(facts)
    customer = bool(scope and scope["value"] == "대고객 서비스")
    externals = [str(x) for x in facts.get("externals", [])]
    metrics = [str(x) for x in facts.get("metrics", [])]

    return {
        "personal_tables": {"on": bool(personal),
                            "evidence": [_ev("table", t) for t in personal[:8]]},
        "sensitive_tables": {"on": bool(sensitive),
                             "evidence": [_ev("table", t) for t in sensitive[:8]]},
        "write_personal": {"on": bool(written),
                           "evidence": [_ev("table", t) for t in written[:8]]},
        "read_personal_customer": {
            "on": bool(read) and customer,
            "evidence": ([_ev("table", t) for t in read[:6]]
                         + (scope["evidence"][:2] if scope else [])),
        },
        "external_calls": {"on": bool(externals),
                           "evidence": [_ev("call", x) for x in externals[:8]]},
        # ★ '없음'을 근거로 삼는 유일한 규칙. 없다는 것은 코드에서 못 찾았다는
        #   뜻이지 실제로 없다는 증명이 아니라, 화면 문구도 그렇게 쓴다.
        "no_metrics": {"on": not metrics,
                       "evidence": [_ev("program", p) for p in
                                    list(facts.get("program_ids") or [])[:6]]},
    }


def suggest(facts: dict[str, Any]) -> dict[str, Any]:
    """정적 분석 사실 → 제안. 사실이 없으면 아무것도 제안하지 않는다."""
    if not facts:
        return {"profile": [], "items": [], "unanswerable": rules()["unanswerable"],
                "facts": {}, "version": rules()["version"]}

    profile = [p for p in (_user_scope(facts), _sensitivity(facts)) if p]
    signals = _signals(facts)

    items: list[dict[str, Any]] = []
    for rule in rules()["items"]:
        sig = signals.get(str(rule["when"]))
        if not sig or not sig["on"]:
            continue
        items.append({
            "no": int(rule["item_no"]),
            "suggest": "identify",
            "confidence": CANDIDATE,
            "because": rule["because"],
            "signal": rule["when"],
            "evidence": sig["evidence"],
        })

    return {
        "profile": profile,
        "items": sorted(items, key=lambda r: r["no"]),
        "unanswerable": rules()["unanswerable"],
        "facts": facts,
        "version": rules()["version"],
    }


__all__ = ["suggest", "rules", "CANDIDATE"]
