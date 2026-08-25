"""진단 준비 API (`/api/audit/…`) — 현장 체크리스트와 시계열.

두 화면은 목적이 하나다: **진단 아이템을 고르는 일을 사람의 기억에서 떼어내는 것.**

* 체크리스트 — 업종·설비를 고르면 과거 진단에서 실제로 나왔던 개선안을 설비별로
  묶어 한 장으로 만든다. 현장 투어에서 종이로 들고 다니며 해당/비해당을 치는 것이
  목적이라, 화면은 인쇄를 1급 기능으로 취급한다.
* 시계열 — 같은 설비가 해가 바뀌며 어떤 값을 보였는지 모은다. "무슨 보일러인데
  몇 년도 것" 만으로 대략이 잡히면 진단 착수의 출발점이 달라진다.

`bind(cfg)` 방식으로 붙는다 (SPA 폴백보다 먼저 등록).

**아이템 후보는 지어내지 않는다.** 위키에 measure 페이지가 없으면 설비 골격만
돌려주고 비어 있음을 그대로 말한다 — 근거 없는 목록을 주면 현장에서 신뢰를 잃는다.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from ..config import Config
from ..ediag.store import WikiStore
from ..kb import taxonomy

router = APIRouter(prefix="/api/audit", tags=["audit-prep"])

_cfg: Config | None = None

#: 설비별 기본 실측 항목. 회의에서 나온 "줄자를 들고 다니며 몇 센티미터까지 적는"
#: 그 자리다. 값을 채우는 것은 사람이고, 화면은 **적을 칸이 있다는 것**만 보장한다.
FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "보일러": ("용량(t/h)", "배가스 온도(℃)", "공기비(O2 %)", "연간 가동(h)"),
    "냉동기": ("용량(RT)", "COP(실측)", "냉수 출구온도(℃)", "연간 가동(h)"),
    "공기압축기": ("토출압(kg/㎠)", "정격출력(kW)", "부하율(%)", "누설 추정(%)"),
    "송풍기": ("풍량(㎥/min)", "정압(mmAq)", "전동기(kW)", "제어 방식"),
    "펌프": ("유량(㎥/h)", "양정(m)", "전동기(kW)", "제어 방식"),
    "건조기": ("증발량(kg/h)", "입·출구 함수율(%)", "열원", "배기 온도(℃)"),
    "가열로": ("조업 온도(℃)", "배가스 온도(℃)", "단열 상태", "연간 가동(h)"),
    "공조기": ("풍량(㎥/min)", "외기 도입(%)", "전동기(kW)", "제어 방식"),
    "조명": ("등종류", "수량(개)", "점등시간(h/d)", "대체 가능"),
}
_DEFAULT_FIELDS = ("용량", "수량", "연간 가동(h)", "비고")

#: 설비 별칭. 택소노미가 부르는 이름과 보고서가 쓰는 말이 다르다 —
#: "송풍기" 로 등록된 설비가 카드에는 "루츠 블로워" 로 적힌다.
EQUIPMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "송풍기": ("블로워", "blower", "팬", "fan"),
    "공기압축기": ("압축기", "컴프레서", "compressor", "공압"),
    "냉동기": ("칠러", "chiller", "냉동", "흡수식"),
    "보일러": ("boiler", "증기", "스팀", "노통연관", "관류"),
    "건조기": ("건조", "dryer", "디스크"),
    "펌프": ("pump",),
    "탈수기": ("탈수", "원심", "스크류"),
    "파쇄기": ("파쇄", "crusher", "분쇄"),
    "가열로": ("가열", "furnace", "소성", "킬른"),
    "공조기": ("공조", "ahu", "외기"),
    "조명": ("led", "등기구", "형광"),
    "탈취설비": ("탈취", "악취"),
}


def _matches_equipment(equipment: str, haystack: str) -> bool:
    """설비 이름 또는 그 별칭이 문자열에 있는가."""
    low = haystack.lower()
    if equipment.lower() in low:
        return True
    return any(a.lower() in low for a in EQUIPMENT_ALIASES.get(equipment, ()))


def _page_sector(fm: dict) -> str:
    """페이지가 말하는 업종 코드.

    `domain`(building/industrial/renewable)은 업종 코드가 **아니다.** 둘을 섞으면
    택소노미 조회가 KeyError 로 터진다 — 실제로 그렇게 터뜨린 적이 있다.
    """
    return str(fm.get("sector") or "")


def _sector_name(code: str, lang: str) -> str:
    if not code:
        return ""
    try:
        return taxonomy.sector_name(code, lang)
    except KeyError:
        return code


def bind(cfg: Config) -> APIRouter:
    global _cfg
    _cfg = cfg
    return router


def _config() -> Config:
    if _cfg is None:  # pragma: no cover - bind 없이 부르면 배선이 잘못된 것이다
        raise RuntimeError("audit router is not bound")
    return _cfg


def _dir() -> Path:
    d = _config().checklist_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _store() -> WikiStore:
    return WikiStore(_config().wiki_dir)


def _slug(value: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", (value or "").strip().lower()).strip("-")
    return s[:48] or uuid.uuid4().hex[:8]


# --------------------------------------------------------------------------- #
# 체크리스트 초안
# --------------------------------------------------------------------------- #
def _measure_candidates(sector: str) -> list[dict[str, Any]]:
    """위키의 measure 페이지에서 이 업종에 쓸 만한 개선안을 모은다.

    사업장에 종속된 값은 가져오지 않는다 — 카드가 담고 있는 것은 조건이고,
    수치는 진단 건에서 온다.
    """
    try:
        pages = _store().pages(page_type="measure")
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for p in pages:
        if p.errors:
            continue
        fm = p.front_matter or {}
        page_sector = _page_sector(fm)
        tags = [str(x) for x in (p.tags or [])]
        out.append(
            {
                "stable_id": p.stable_id,
                "title": p.title,
                "sector": page_sector,
                "tags": tags,
                "status": p.status,
                # 업종이 같거나, 업종이 안 박힌 범용 카드면 후보로 본다.
                "match": (page_sector == sector) or not page_sector,
            }
        )
    return out


def _fields_for(equipment: str) -> list[str]:
    for key, fields in FIELD_HINTS.items():
        if key in equipment or equipment in key:
            return list(fields)
    return list(_DEFAULT_FIELDS)


@router.get("/checklist/draft")
def checklist_draft(
    sector: str = Query(...),
    lang: str = Query("ko"),
) -> dict[str, Any]:
    """업종을 고르면 설비별 골격 + 위키에서 찾은 아이템 후보를 돌려준다. 저장하지 않는다."""
    try:
        profile = taxonomy.get(sector)
    except KeyError:
        raise HTTPException(400, f"미정의 업종: {sector}")

    candidates = _measure_candidates(sector)
    used: set[str] = set()
    groups: list[dict[str, Any]] = []

    for equipment in profile.key_equipment:
        items: list[dict[str, Any]] = []
        for c in candidates:
            if not c["match"]:
                continue
            haystack = f"{c['title']} {' '.join(c['tags'])} {c['stable_id']}"
            if _matches_equipment(equipment, haystack):
                items.append(
                    {
                        "id": uuid.uuid4().hex[:8],
                        "name": c["title"],
                        "source": c["stable_id"],
                        "checked": "",
                        "note": "",
                    }
                )
                used.add(c["stable_id"])
        groups.append(
            {
                "equipment": equipment,
                "fields": _fields_for(equipment),
                "items": items,
            }
        )

    # 설비에 붙지 못한 카드는 버리지 않는다 — 분류가 애매한 것이지 쓸모없는 것이 아니다.
    leftovers = [c for c in candidates if c["match"] and c["stable_id"] not in used]
    if leftovers:
        groups.append(
            {
                "equipment": "기타",
                "fields": list(_DEFAULT_FIELDS),
                "items": [
                    {
                        "id": uuid.uuid4().hex[:8],
                        "name": c["title"],
                        "source": c["stable_id"],
                        "checked": "",
                        "note": "",
                    }
                    for c in leftovers
                ],
            }
        )

    total_items = sum(len(g["items"]) for g in groups)
    return {
        "sector": sector,
        "sector_name": taxonomy.sector_name(sector, lang),
        "unit_basis": profile.unit_basis,
        "energy_sources": list(profile.energy_sources),
        "groups": groups,
        "item_count": total_items,
        # 위키가 비어 있으면 설비 골격만 나간다. 화면이 이 사실을 그대로 말해야 한다.
        "from_wiki": total_items > 0,
        "wiki_measures": len(candidates),
    }


# --------------------------------------------------------------------------- #
# 체크리스트 보관 — 팀이 함께 보는 표준 서식이 목적이다
# --------------------------------------------------------------------------- #
def _read(cid: str) -> dict[str, Any] | None:
    f = _dir() / f"{cid}.json"
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


@router.get("/checklists")
def checklists() -> dict[str, Any]:
    out = []
    for f in sorted(_dir().glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append(
            {
                "id": d.get("id", f.stem),
                "title": d.get("title", f.stem),
                "sector": d.get("sector", ""),
                "subsector": d.get("subsector", ""),
                "site": d.get("site", ""),
                "owner": d.get("owner", ""),
                "item_count": sum(len(g.get("items", [])) for g in d.get("groups", [])),
                "updated_at": d.get("updated_at", ""),
            }
        )
    out.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"checklists": out}


@router.get("/checklists/{cid}")
def checklist(cid: str) -> dict[str, Any]:
    d = _read(cid)
    if d is None:
        raise HTTPException(404, "체크리스트를 찾을 수 없습니다")
    return d


@router.post("/checklists")
def save_checklist(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    title = str(payload.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "제목이 필요합니다")

    cid = str(payload.get("id") or "").strip() or f"cl-{_slug(title)}-{uuid.uuid4().hex[:4]}"
    from datetime import datetime, timezone

    record = {
        "id": cid,
        "title": title,
        "sector": str(payload.get("sector") or ""),
        # 회의에서 지적된 소분류. 자동 분류가 아직 없어 자유 입력으로 받는다 —
        # 보고서가 쌓이면 여기를 닫힌 집합으로 바꾼다.
        "subsector": str(payload.get("subsector") or ""),
        "site": str(payload.get("site") or ""),
        "homepage": str(payload.get("homepage") or ""),
        "owner": str(payload.get("owner") or ""),
        "note": str(payload.get("note") or ""),
        "groups": payload.get("groups") or [],
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (_dir() / f"{cid}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


@router.delete("/checklists/{cid}")
def delete_checklist(cid: str) -> dict[str, Any]:
    f = _dir() / f"{cid}.json"
    if not f.is_file():
        raise HTTPException(404, "체크리스트를 찾을 수 없습니다")
    f.unlink()
    return {"deleted": cid}


# --------------------------------------------------------------------------- #
# 시계열
# --------------------------------------------------------------------------- #
_YEAR = re.compile(r"(19|20)\d{2}")


def _year_of(page) -> str:
    """페이지가 말하는 연도. 측정 기간이 우선이고, 없으면 출처·적재 시각을 본다."""
    fm = page.front_matter or {}
    for key in ("measurement_period", "period", "measurementPeriod"):
        m = _YEAR.search(str(fm.get(key) or ""))
        if m:
            return m.group(0)
    for span in page.source_span or []:
        m = _YEAR.search(str(span.get("doc", "")))
        if m:
            return m.group(0)
    prov = fm.get("provenance") or {}
    m = _YEAR.search(str(prov.get("ingested_at", "")))
    return m.group(0) if m else ""


@router.get("/timeseries")
def timeseries(
    sector: str = Query(""),
    page_type: str = Query("", alias="type"),
    lang: str = Query("ko"),
) -> dict[str, Any]:
    """연도축 집계. 위키가 원본이고, 적재 이력은 참고로만 곁들인다."""
    try:
        pages = _store().pages()
    except Exception:
        pages = []

    rows: list[dict[str, Any]] = []
    for p in pages:
        if p.errors:
            continue
        fm = p.front_matter or {}
        p_sector = _page_sector(fm)
        if sector and p_sector != sector:
            continue
        if page_type and p.type != page_type:
            continue
        rows.append(
            {
                "stable_id": p.stable_id,
                "title": p.title,
                "type": p.type,
                "sector": p_sector,
                "sector_name": _sector_name(p_sector, lang),
                # domain 은 업종과 다른 축이다 (building/industrial/renewable).
                "domain": str(fm.get("domain") or ""),
                "year": _year_of(p),
                "status": p.status,
                "numeric_verified": bool(p.numeric_verified),
                "tags": [str(x) for x in (p.tags or [])],
            }
        )

    years = sorted({r["year"] for r in rows if r["year"]})
    by_year: dict[str, dict[str, Any]] = {
        y: {"year": y, "pages": 0, "verified": 0, "by_type": {}} for y in years
    }
    for r in rows:
        y = r["year"]
        if not y:
            continue
        slot = by_year[y]
        slot["pages"] += 1
        if r["numeric_verified"]:
            slot["verified"] += 1
        slot["by_type"][r["type"]] = slot["by_type"].get(r["type"], 0) + 1

    # 적재 이력(지식 데이터베이스)은 위키와 별개 축이다. 위키가 비어 있어도
    # 문서가 얼마나 들어와 있는지는 보여 줘야 다음 할 일이 보인다.
    ledger_years: dict[str, int] = {}
    ledger = _config().kb_dir / "ledger.jsonl"
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = _YEAR.search(str(d.get("ingested_at", "")))
            if m:
                ledger_years[m.group(0)] = ledger_years.get(m.group(0), 0) + 1

    return {
        "rows": rows,
        "years": years,
        "by_year": [by_year[y] for y in years],
        "undated": sum(1 for r in rows if not r["year"]),
        "ledger_by_year": [{"year": y, "documents": n} for y, n in sorted(ledger_years.items())],
        "sectors": taxonomy.as_dict(lang),
    }
