"""진단 보고서에서 사실을 뽑는다 — 규칙만으로, LLM 없이.

LLM 이 하는 일은 "원문에서 입력값을 정확히 뽑는" 것이라고 기획서는 적었다. 그런데
에너지 진단 보고서는 입력값이 **표와 계산식**에 있고, 둘 다 형태가 정해져 있다.
정해진 형태를 읽는 데 LLM 을 쓰면 같은 문서가 실행할 때마다 다른 값을 내놓는다.
그래서 이 모듈은 규칙으로만 읽는다 — 결정론적이고, 재현 가능하고, 틀리면 고칠 수 있다.

세 갈래로 읽는다.

1. **표** — 설비현황·단가·연간사용량 산정·집계표·투자비. 헤더 어휘로 표를 찾는다.
2. **계산식** — 보고서는 식을 그대로 적는다. ``= 36(㎏/h) × 10(h/d) × 300(d/y) × 70(%)
   = 75,600(㎏)`` 같은 줄에서 **입력과 결과를 함께** 얻는다. 곱을 다시 계산해 원문의
   결과와 대조하면 그 자리에서 검산이 된다.
3. **서술** — 문제점·개선방안 문단. 수치는 여기서 뽑지 않는다.

개인정보는 뽑지 않는다. 대표자·담당자·연락처·사업자등록번호는 필드 이름으로 걸러
아예 결과에 넣지 않고, 몇 건을 걸렀는지만 남긴다 — 위키는 사내 공유물이라 원문에
있다고 그대로 옮기면 안 된다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import calc
from .units import UnitTable, load

#: 값째로 옮기지 않는 필드. 이름이 걸리면 값을 버린다.
PII_KEYS: tuple[str, ...] = (
    "대표자", "담당자", "전화", "연락처", "휴대", "팩스", "fax", "e-mail", "email",
    "이메일", "사업자등록", "주민", "성명", "진단수행자", "수행자",
)

NUM = r"-?[\d,]+(?:\.\d+)?"
#: `36(㎏/h)` `7,200(h/y)` `90.72(toe)` — 숫자 뒤 괄호 단위. 단위는 12자를 넘지 않는다.
NUM_UNIT = re.compile(rf"({NUM})\s*[\(\[]\s*([^)\]]{{0,14}}?)\s*[\)\]]")
BARE_NUM = re.compile(NUM)

MULT = "×"


def _f(cell: Any) -> float | None:
    """셀에서 첫 숫자를 뽑는다. `18대` `약 3,000(h/y)` `-` 를 모두 견딘다."""
    if cell is None:
        return None
    m = BARE_NUM.search(str(cell).replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _txt(cell: Any) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip()


def _is_pii(key: str) -> bool:
    low = _txt(key).replace(" ", "").lower()
    return any(k.replace(" ", "").lower() in low for k in PII_KEYS)


# --------------------------------------------------------------------------- #
# 근거 스팬
# --------------------------------------------------------------------------- #
@dataclass
class Span:
    """이 사실이 원문 어디서 왔는가. front-matter 의 source_span 이 되는 자료."""

    doc: str
    pages: list[int]
    section: str = ""
    anchor: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = {"doc": self.doc, "pages": self.pages}
        if self.section:
            d["section"] = self.section
        if self.anchor:
            d["anchor"] = self.anchor
        return d


@dataclass
class TableFact:
    """표 한 줄에서 뽑은 사실."""

    kind: str
    fields: dict[str, Any]
    span: Span

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "fields": self.fields, "span": self.span.to_dict()}


# --------------------------------------------------------------------------- #
# 표 찾기
# --------------------------------------------------------------------------- #
def _header_text(table: Any) -> str:
    return " ".join(_txt(h) for h in (table.header or []))


def find_tables(doc: Any, *terms: str, all_of: bool = True) -> list[Any]:
    """헤더 어휘로 표를 찾는다. 페이지 번호로 찾지 않는다 — 보고서마다 쪽이 다르다."""
    out = []
    for t in doc.tables:
        head = _header_text(t).replace(" ", "")
        hit = [term.replace(" ", "") in head for term in terms]
        if (all(hit) if all_of else any(hit)):
            out.append(t)
    return out


def _col(table: Any, *terms: str) -> int | None:
    for i, h in enumerate(table.header or []):
        flat = _txt(h).replace(" ", "")
        if any(term.replace(" ", "") in flat for term in terms):
            return i
    return None


def _span(doc: Any, table: Any, section: str = "") -> Span:
    return Span(doc=doc.filename, pages=[table.page], section=section, anchor=table.anchor)


# --------------------------------------------------------------------------- #
# 1) 사업장 개요
# --------------------------------------------------------------------------- #
def facility(doc: Any) -> tuple[dict[str, Any], int]:
    """업체 일반현황 표에서 개인정보가 아닌 항목만 가져온다.

    돌려주는 두 번째 값은 **버린 개인정보 항목 수**다. 0 이 아닌 것이 정상이고,
    그 사실 자체가 감리에서 "원문에 있던 연락처를 어떻게 했는가" 의 답이 된다.
    """
    tables = find_tables(doc, "업체명") or find_tables(doc, "업 체 명")
    if not tables:
        return {}, 0
    t = tables[0]
    out: dict[str, Any] = {}
    dropped = 0
    rows = [list(t.header or []), *t.rows]
    for row in rows:
        for i in range(0, len(row) - 1, 2):
            key, value = _txt(row[i]), _txt(row[i + 1])
            if not key or not value:
                continue
            if _is_pii(key):
                dropped += 1
                continue
            out[key.replace(" ", "")] = value
    out["_span"] = _span(doc, t, "Ⅰ.1 일반현황").to_dict()
    return out, dropped


# --------------------------------------------------------------------------- #
# 2) 설비 현황
# --------------------------------------------------------------------------- #
def _page_text(doc: Any) -> dict[int, str]:
    out: dict[int, str] = {}
    for b in doc.text_blocks:
        out[b.page] = out.get(b.page, "") + "\n" + b.text
    return out


BRACKET = re.compile(r"[\[\【]\s*([^\]\】]{2,40})\s*[\]\】]")


def _family(caption: str, page_text: str) -> str:
    """표가 어느 설비의 표인가. 표 제목(`[ 루츠블로워 설치현황 ]`)이 유일한 단서다.

    설비 표의 첫 열은 설비명이 아니라 **설치 위치**인 경우가 흔하다(`2차 숙성실`).
    위치를 설비명으로 올리면 위키에 '건조실' 이라는 설비가 생긴다.
    """
    from . import terms as _terms
    candidates = [caption, *BRACKET.findall(page_text or "")]
    for cand in candidates:
        flat = re.sub(r"\s+", "", cand or "")
        for ko, _en in _terms.EQUIPMENT_TERMS:
            if ko in flat:
                return ko
    return ""


def _merge_unnamed(groups: dict[tuple, dict[str, Any]], order: list[tuple]) -> None:
    """이름을 못 붙인 무리를 같은 제원의 이름 있는 무리에 합친다.

    같은 설비가 개요 표(제목 없음)와 상세 표(`[ 루츠블로워 설치현황 ]`)에 두 번 나오면,
    앞의 것만 이름을 못 얻는다. 그대로 두면 같은 설비가 위키에 두 장 생긴다.
    용량·단위·모델이 같으면 같은 설비로 본다.
    """
    named = {
        (g["capacity"], g["capacity_unit"], g["model"]): key
        for key, g in groups.items() if not g["needs_naming"]
    }
    for key in list(order):
        g = groups.get(key)
        if g is None or not g["needs_naming"]:
            continue
        target_key = named.get((g["capacity"], g["capacity_unit"], g["model"]))
        if target_key is None or target_key == key:
            continue
        target = groups[target_key]
        for inst in g["installations"]:
            if inst not in target["installations"]:
                target["installations"].append(inst)
                target["total_count"] += inst.get("count") or 0.0
        for page, anchor in zip(g["pages"], g["anchors"]):
            if page not in target["pages"]:
                target["pages"].append(page)
                target["anchors"].append(anchor)
        del groups[key]
        order.remove(key)


def equipment(doc: Any) -> list[TableFact]:
    """설비현황 표. `제작사` 열이 있는 표를 설비 표로 본다.

    같은 설비가 여러 표에 나오므로(설치현황·진단내용) **용량·모델이 같으면 한 설비로
    묶고** 설치 위치와 대수를 목록으로 들고 간다. 표마다 페이지를 따로 만들면 같은
    설비가 위키에 두 번 생기고, 그 순간 '설비 1대당 어떤 개선안' 이라는 연결이 깨진다.
    """
    from . import terms as _terms

    pages = _page_text(doc)
    groups: dict[tuple, dict[str, Any]] = {}
    order: list[tuple] = []
    for t in find_tables(doc, "제작사"):
        name_col = _col(t, "구분", "위치", "명칭") or 0
        cap_col = _col(t, "용량")
        count_col = _col(t, "대수", "수량")
        maker_col = _col(t, "제작사")
        year_col = _col(t, "제작년도", "제작 년도")
        model_col = _col(t, "모델")
        fuel_col = _col(t, "연료")
        cap_unit = ""
        if cap_col is not None:
            m = re.search(r"[\(\[]\s*([^)\]]+)\s*[\)\]]", _txt(t.header[cap_col]))
            cap_unit = m.group(1) if m else ""
        family = _family(t.caption, pages.get(t.page, ""))

        for row in t.rows:
            raw_name = _txt(row[name_col]) if name_col < len(row) else ""
            if not raw_name or raw_name.replace(" ", "") in ("계", "합계", "소계"):
                continue
            term, needs_naming = _terms.ascii_term(raw_name)
            location = ""
            name = raw_name
            if _terms.is_location(raw_name):
                needs_naming = True
            if needs_naming and family:
                # 첫 열이 위치였다. 설비명은 표 제목에서 온다.
                name, location = family, raw_name
                term, needs_naming = _terms.ascii_term(family)
            capacity = _f(row[cap_col]) if cap_col is not None and cap_col < len(row) else None
            model = _txt(row[model_col]) if model_col is not None and model_col < len(row) else ""
            key = (term, capacity, cap_unit, model)
            if key not in groups:
                order.append(key)
                groups[key] = {
                    "term": term, "name": name, "needs_naming": needs_naming,
                    "capacity": capacity, "capacity_unit": cap_unit, "model": model,
                    "maker": _txt(row[maker_col]) if maker_col is not None and maker_col < len(row) else "",
                    "year": _txt(row[year_col]) if year_col is not None and year_col < len(row) else "",
                    "fuel": _txt(row[fuel_col]) if fuel_col is not None and fuel_col < len(row) else "",
                    "installations": [], "total_count": 0.0, "pages": [], "anchors": [],
                }
            g = groups[key]
            count = _f(row[count_col]) if count_col is not None and count_col < len(row) else None
            if location:
                known = {(i["location"], i["count"]) for i in g["installations"]}
                if (location, count) not in known:
                    g["installations"].append({"location": location, "count": count})
                    g["total_count"] += count or 0.0
            elif count is not None:
                # 위치 구분이 없는 표는 같은 설비가 여러 표에 반복될 뿐이다.
                # 더하면 대수가 표 수만큼 부풀려진다.
                g["total_count"] = max(g["total_count"], count)
            if t.page not in g["pages"]:
                g["pages"].append(t.page)
                g["anchors"].append(t.anchor)

    _merge_unnamed(groups, order)

    facts: list[TableFact] = []
    for key in order:
        g = groups[key]
        facts.append(TableFact("equipment", g, Span(
            doc=doc.filename, pages=list(g["pages"]), section="설비현황",
            anchor=", ".join(g["anchors"]))))
    return facts


# --------------------------------------------------------------------------- #
# 3) 단가 — SSOT 와 대조한다
# --------------------------------------------------------------------------- #
def prices(doc: Any, table: UnitTable | None = None) -> list[calc.Check]:
    """보고서의 적용 단가를 `units.yaml` 과 대조한다.

    단가는 개정된다. 보고서가 쓴 단가와 우리 SSOT 가 다르면 둘 중 하나가 낡은 것이고,
    어느 쪽이든 **사람이 봐야 한다.** 조용히 SSOT 로 덮어쓰면 원문 검증이 불가능해진다.
    """
    t = table or load()
    checks: list[calc.Check] = []
    for tb in find_tables(doc, "단가"):
        for row in [list(tb.header or []), *tb.rows]:
            label = _txt(row[0] if row else "")
            joined = " ".join(_txt(c) for c in row)
            value = None
            code = ""
            if "원/kWh" in joined or "원/kwh" in joined.lower():
                m = re.search(rf"({NUM})\s*[\(\[]?\s*원/kWh", joined, re.I)
                value, code = (_f(m.group(1)) if m else None), "price.elec_won_per_kwh"
            elif "원/㎏" in joined or "원/kg" in joined.lower():
                m = re.search(rf"({NUM})\s*[\(\[]?\s*원/(?:㎏|kg)", joined, re.I)
                value, code = (_f(m.group(1)) if m else None), "price.lpg_won_per_kg"
            if value is None or not code:
                continue
            f = t.factor(code)
            checks.append(calc.check(
                f"적용 단가 — {f.label}", f.value, value, f.unit,
                formula=f"units.yaml::{code}",
                inputs={"보고서 표기": value, "SSOT": f.value, "유효기간": f.valid_until},
                source=f"p{tb.page} {label}", table=t,
            ))
    return checks


# --------------------------------------------------------------------------- #
# 4) 연간 전력량 산정 표
# --------------------------------------------------------------------------- #
def power_plan(doc: Any, table: UnitTable | None = None) -> tuple[list[TableFact], list[calc.Check]]:
    """`연간 전력량` 열이 있는 표를 재계산해 대조한다."""
    t = table or load()
    facts: list[TableFact] = []
    checks: list[calc.Check] = []
    for tb in find_tables(doc, "연간 전력량"):
        c_name = _col(tb, "위치", "구분") or 0
        c_count = _col(tb, "수량", "대수")
        c_run = _col(tb, "운전전력")
        c_rated = _col(tb, "정격전력")
        c_hours = _col(tb, "연간가동", "가동 시간", "시간(h/y)")
        c_ratio = _col(tb, "안전률", "부하율")
        c_total = _col(tb, "연간 전력량")
        for row in tb.rows:
            name = _txt(row[c_name]) if c_name < len(row) else ""
            count = _f(row[c_count]) if c_count is not None and c_count < len(row) else None
            power = _f(row[c_run]) if c_run is not None and c_run < len(row) else None
            if power is None and c_rated is not None and c_rated < len(row):
                power = _f(row[c_rated])
            hours = _f(row[c_hours]) if c_hours is not None and c_hours < len(row) else None
            ratio = _f(row[c_ratio]) if c_ratio is not None and c_ratio < len(row) else None
            stated = _f(row[c_total]) if c_total is not None and c_total < len(row) else None
            if None in (count, power, hours, ratio) or stated is None:
                continue
            is_total = name.replace(" ", "") in ("계", "합계", "소계")
            computed = calc.annual_kwh(power, hours, ratio / 100.0, int(count))
            facts.append(TableFact("power_row", {
                "name": name, "count": count, "power_kw": power, "hours": hours,
                "load_pct": ratio, "annual_kwh": stated, "is_total": is_total,
            }, _span(doc, tb, "연간 소비전력 산정")))
            if is_total:
                # 계 행의 평균 운전전력((24.7))으로는 합계가 나오지 않는다. 합계는
                # 개별 행의 합으로 검산해야 한다 — 아래 total 검산이 그 몫이다.
                continue
            checks.append(calc.check(
                f"연간 전력량 — {name}", computed, stated, "kWh/y",
                formula="대수 × 운전전력 × 연간가동시간 × 부하율",
                inputs={"대수": count, "전력(kW)": power, "시간(h/y)": hours, "부하율(%)": ratio},
                source=f"p{tb.page} {tb.anchor}", table=t,
            ))
        rows = [f for f in facts if f.span.anchor == tb.anchor]
        parts = [f for f in rows if not f.fields["is_total"]]
        totals = [f for f in rows if f.fields["is_total"]]
        if parts and totals:
            checks.append(calc.check(
                "연간 전력량 — 합계", sum(f.fields["annual_kwh"] for f in parts),
                totals[0].fields["annual_kwh"], "kWh/y",
                formula="행 합계", inputs={"행": len(parts)},
                source=f"p{tb.page} {tb.anchor}", table=t,
            ))
    return facts, checks


# --------------------------------------------------------------------------- #
# 5) 보일러 가동현황 표
# --------------------------------------------------------------------------- #
def boiler_plan(doc: Any, table: UnitTable | None = None) -> list[TableFact]:
    t = table or load()
    facts: list[TableFact] = []
    for tb in find_tables(doc, "연료소비량"):
        c_name = _col(tb, "구분") or 0
        c_rate = _col(tb, "연료소비량")
        c_hpd = _col(tb, "운전시간")
        c_days = _col(tb, "가동 일수", "가동일수")
        c_ratio = _col(tb, "부하율")
        c_price = _col(tb, "단가")
        for row in tb.rows:
            rate = _f(row[c_rate]) if c_rate is not None and c_rate < len(row) else None
            hpd = _f(row[c_hpd]) if c_hpd is not None and c_hpd < len(row) else None
            days = _f(row[c_days]) if c_days is not None and c_days < len(row) else None
            ratio = _f(row[c_ratio]) if c_ratio is not None and c_ratio < len(row) else None
            if None in (rate, hpd, days, ratio):
                continue
            kg = calc.annual_fuel_kg(rate, hpd, days, ratio / 100.0)
            facts.append(TableFact("boiler_row", {
                "name": _txt(row[c_name]) if c_name < len(row) else "",
                "rate_kg_h": rate, "hours_per_day": hpd, "days": days, "load_pct": ratio,
                "stated_price": _f(row[c_price]) if c_price is not None and c_price < len(row) else None,
                "annual_kg": kg,
                "annual_toe": calc.toe_from_lpg_kg(kg, t),
                "annual_tco2eq": calc.tco2eq_from_lpg_kg(kg, t),
                "annual_cost_kwon": calc.lpg_cost_kwon(kg, t),
            }, _span(doc, tb, "보일러 가동현황")))
    return facts


# --------------------------------------------------------------------------- #
# 5-1) 현장 계측 결과
# --------------------------------------------------------------------------- #
def measurements(doc: Any) -> list[TableFact]:
    """전력 측정 표. 측정값과 부하율이 함께 있는 표를 계측 결과로 본다.

    부하율이 100%를 넘는 행이 여기서 나온다 — 정격을 넘겨 도는 설비는 노후·과부하의
    직접 증거라 인사이트 페이지의 근거가 된다.
    """
    facts: list[TableFact] = []
    for tb in find_tables(doc, "측정전력"):
        c_tag = _col(tb, "기번", "구분") or 0
        c_when = _col(tb, "측정일자")
        c_load = _col(tb, "부하율")
        for row in tb.rows:
            tag = _txt(row[c_tag]) if c_tag < len(row) else ""
            load = _f(row[c_load]) if c_load is not None and c_load < len(row) else None
            # 측정전력 열은 '전력범위 / 평균' 으로 쪼개져 있다. 평균은 범위 열 다음이다.
            avg = None
            for cell in row:
                v = _txt(cell)
                if re.fullmatch(rf"{NUM}", v.replace(" ", "")) and v not in (tag,):
                    n = _f(v)
                    if n is not None and (load is None or n != load):
                        avg = n
            if not tag or load is None or avg is None:
                continue
            facts.append(TableFact("measurement", {
                "tag": tag,
                "when": _txt(row[c_when]) if c_when is not None and c_when < len(row) else "",
                "avg_kw": avg, "load_pct": load,
            }, _span(doc, tb, "현장 계측")))
    return facts


# --------------------------------------------------------------------------- #
# 6) 부속설비 사업 전·후
# --------------------------------------------------------------------------- #
def aux_equipment(doc: Any) -> tuple[list[TableFact], list[calc.Check]]:
    """`설비명` + 사업전/사업후 용량 표. 합계 행을 항목 합과 대조한다."""
    facts: list[TableFact] = []
    checks: list[calc.Check] = []
    for tb in find_tables(doc, "설비명"):
        head = _header_text(tb)
        if "사 업 전" not in head and "사업전" not in head.replace(" ", ""):
            continue
        c_name = _col(tb, "설비명")
        # 헤더가 병합돼 두 번째 행이 실제 열 이름(수량/용량)인 형태다.
        sub = tb.rows[0] if tb.rows else []
        cap_cols = [i for i, c in enumerate(sub) if "용량" in _txt(c)]
        if len(cap_cols) < 2 or c_name is None:
            continue
        before_col, after_col = cap_cols[0], cap_cols[1]
        before_sum = after_sum = 0.0
        stated_before = stated_after = None
        for row in tb.rows[1:]:
            name = _txt(row[c_name]) if c_name < len(row) else ""
            b = _f(row[before_col]) if before_col < len(row) else None
            a = _f(row[after_col]) if after_col < len(row) else None
            if name.replace(" ", "") in ("합계", "계"):
                stated_before, stated_after = b, a
                continue
            if not name:
                continue
            facts.append(TableFact("aux_row", {
                "name": name, "before_kw": b or 0.0, "after_kw": a or 0.0,
            }, _span(doc, tb, "부속설비 사업 전·후")))
            before_sum += b or 0.0
            after_sum += a or 0.0
        if stated_before is not None:
            checks.append(calc.check(
                "부속설비 합계 — 사업전", before_sum, stated_before, "kW",
                formula="항목 용량 합", inputs={"항목": len(facts)},
                source=f"p{tb.page} {tb.anchor}"))
        if stated_after is not None:
            checks.append(calc.check(
                "부속설비 합계 — 사업후", after_sum, stated_after, "kW",
                formula="항목 용량 합", inputs={"항목": len(facts)},
                source=f"p{tb.page} {tb.anchor}"))
    return facts, checks


# --------------------------------------------------------------------------- #
# 7) 개선 전·후 집계표
# --------------------------------------------------------------------------- #
def before_after(doc: Any) -> tuple[list[TableFact], list[calc.Check]]:
    """집계표의 증감(b-a)을 다시 계산한다.

    이 표가 보고서의 결론이다. 여기 숫자 하나가 틀리면 회수기간이 틀리고 투자 판단이
    틀린다. 그런데 손으로 옮겨 적는 표라 실제로 가장 자주 틀린다.
    """
    facts: list[TableFact] = []
    checks: list[calc.Check] = []
    for tb in find_tables(doc, "개선전", "개선후"):
        c_group = 0
        c_item = _col(tb, "항목")
        c_unit = _col(tb, "단위")
        c_before = _col(tb, "개선전")
        c_after = _col(tb, "개선후")
        c_delta = _col(tb, "증감")
        if None in (c_item, c_before, c_after):
            continue
        group = ""
        for row in tb.rows:
            group = _txt(row[c_group]) or group
            item = _txt(row[c_item]) if c_item < len(row) else ""
            unit = _txt(row[c_unit]) if c_unit is not None and c_unit < len(row) else ""
            before = _f(row[c_before]) if c_before < len(row) else None
            after = _f(row[c_after]) if c_after < len(row) else None
            delta = _f(row[c_delta]) if c_delta is not None and c_delta < len(row) else None
            if before is None or after is None or not item:
                continue
            facts.append(TableFact("aggregate_row", {
                "group": group, "item": item, "unit": unit,
                "before": before, "after": after, "stated_delta": delta,
            }, _span(doc, tb, "사업 전·후 집계표")))
            if delta is None:
                continue
            # 원문은 감소를 음수로도, 절댓값으로도 적는다. 부호 규약이 섞여 있으므로
            # 절댓값으로 비교하고, 부호 불일치는 따로 표시하지 않는다.
            checks.append(calc.check(
                f"집계표 증감 — {group} {item}", abs(after - before), abs(delta), unit or "",
                formula="개선후 − 개선전",
                inputs={"개선전": before, "개선후": after},
                source=f"p{tb.page} {tb.anchor}"))
    return facts, checks


# --------------------------------------------------------------------------- #
# 8) 투자비 · 회수기간
# --------------------------------------------------------------------------- #
def investment(doc: Any) -> dict[str, Any]:
    """투자비 표(합계)와 본문의 회수기간을 함께 읽는다."""
    out: dict[str, Any] = {}
    for tb in find_tables(doc, "금 액", all_of=False) + find_tables(doc, "금액", all_of=False):
        c_amount = _col(tb, "금 액", "금액")
        if c_amount is None:
            continue
        items = []
        total = None
        for row in tb.rows:
            label = _txt(row[1]) if len(row) > 1 else ""
            first = _txt(row[0]) if row else ""
            amount = _f(row[c_amount]) if c_amount < len(row) else None
            if amount is None:
                continue
            if "합" in first or "합" in label:
                total = amount
            elif label:
                items.append({"label": label, "amount_kwon": amount})
        if total is not None:
            out = {"items": items, "total_kwon": total,
                   "span": _span(doc, tb, "투자비").to_dict()}
            break

    # 회수기간은 제목 줄과 값 줄이 나뉘어 있다.
    #   라. 투자비 회수기간 : 투자비 ÷ 연간 절감금액
    #   = 2,269,000(천원) ÷ 496,282(천원/년)
    #   = 4.6 (년)
    # 그래서 제목 뒤 몇 줄을 함께 본다.
    m = re.search(r"회수기간(.{0,200}?)=\s*(" + NUM + r")\s*\(?\s*년", doc.full_text, re.S)
    if m:
        out["stated_payback_years"] = _f(m.group(2))
    return out


# --------------------------------------------------------------------------- #
# 9) 본문 계산식 — 원문이 적어 둔 식을 다시 계산한다
# --------------------------------------------------------------------------- #
@dataclass
class Formula:
    line: str
    page: int
    factors: list[tuple[float, str]]
    stated: float
    stated_unit: str
    computed: float = 0.0
    scale: float = 1.0
    ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "line": self.line, "page": self.page,
            "factors": [{"value": v, "unit": u} for v, u in self.factors],
            "stated": self.stated, "unit": self.stated_unit,
            "computed": round(self.computed, 4), "scale": self.scale, "ok": self.ok,
        }


#: 천원 표기처럼 자릿수만 다른 경우. 배수가 맞으면 일치로 본다.
_SCALES: tuple[float, ...] = (1.0, 1e-3, 1e3, 1e-6, 1e6)


def formulas(doc: Any, table: UnitTable | None = None) -> tuple[list[Formula], list[calc.Check]]:
    """본문에 적힌 곱셈식을 찾아 다시 계산한다.

    ``= 24(h/d) × 300(d/y) = 7,200(h/y)`` 처럼 보고서는 식을 그대로 적는다. 곱을
    다시 계산해 결과와 대조하면, 옮겨 적다 틀린 값이 그 자리에서 드러난다.
    퍼센트는 비율로 환산한다 — ``70(%)`` 를 70 으로 곱하면 100배가 튄다.
    """
    t = table or load()
    found: list[Formula] = []
    checks: list[calc.Check] = []
    for block in doc.text_blocks:
        for raw in block.text.splitlines():
            line = raw.strip()
            if MULT not in line or "=" not in line:
                continue
            head, _, tail = line.rpartition("=")
            res = NUM_UNIT.search(tail)
            if not res:
                continue
            factors: list[tuple[float, str]] = []
            for i, part in enumerate(head.split(MULT)):
                # 표가 평문으로 눌린 줄에서는 식 앞에 다른 값이 붙어 온다
                # (`195(원/kWh) 90(kW) 10(h) × 300(d)`). 첫 조각은 **마지막** 값이
                # 피연산자다 — 첫 값을 잡으면 엉뚱한 곱이 되어 오탐이 쏟아진다.
                hits = list(NUM_UNIT.finditer(part))
                if not hits:
                    continue
                m = hits[-1] if i == 0 else hits[0]
                try:
                    factors.append((float(m.group(1).replace(",", "")), m.group(2).strip()))
                except ValueError:
                    continue
            if len(factors) < 2:
                continue
            product = 1.0
            for value, unit in factors:
                product *= (value / 100.0) if unit.strip() == "%" else value
            stated = float(res.group(1).replace(",", ""))
            unit = res.group(2).strip()
            best = min(_SCALES, key=lambda s: abs(product * s - stated)
                       / max(abs(stated), t.abs_floor))
            f = Formula(line=line, page=block.page, factors=factors,
                        stated=stated, stated_unit=unit,
                        computed=product * best, scale=best)
            f.ok = abs(f.computed - stated) / max(abs(stated), t.abs_floor) <= t.rel_tolerance
            found.append(f)
            checks.append(calc.check(
                f"본문 계산식 (p{block.page})", f.computed, stated, unit,
                formula=" × ".join(f"{v:,.6g}({u})" for v, u in factors),
                inputs={"원문": line[:120], "자릿수 보정": best},
                source=f"p{block.page}", table=t))
    return found, checks


# --------------------------------------------------------------------------- #
# 10) 서술 — 문제점 · 개선방안
# --------------------------------------------------------------------------- #
SECTION_HEADS: tuple[tuple[str, str], ...] = (
    ("problem", "문제점"),
    ("improvement", "개선방안"),
    ("scope", "사업범위"),
    ("background", "사업지원 배경"),
)


def narratives(doc: Any) -> list[dict[str, Any]]:
    """제목 어휘로 문단을 자른다. 수치는 여기서 뽑지 않는다 — 서술은 서술로만 쓴다."""
    out: list[dict[str, Any]] = []
    for block in doc.text_blocks:
        lines = block.text.splitlines()
        for i, line in enumerate(lines):
            flat = line.replace(" ", "")
            for kind, head in SECTION_HEADS:
                if head.replace(" ", "") not in flat:
                    continue
                body: list[str] = []
                for nxt in lines[i + 1:]:
                    stripped = nxt.strip()
                    if not stripped:
                        continue
                    if re.match(r"^\s*(?:[가-힣]\.|\d+[.)]|[ⅠⅡⅢⅣ])\s", nxt) and body:
                        break
                    body.append(stripped)
                    if len(body) >= 12:
                        break
                if body:
                    out.append({"kind": kind, "heading": line.strip(),
                                "page": block.page, "lines": body})
    return out


# --------------------------------------------------------------------------- #
# 통합
# --------------------------------------------------------------------------- #
@dataclass
class Extraction:
    doc_hash: str
    filename: str
    facility: dict[str, Any] = field(default_factory=dict)
    pii_dropped: int = 0
    equipment: list[TableFact] = field(default_factory=list)
    power: list[TableFact] = field(default_factory=list)
    measurements: list[TableFact] = field(default_factory=list)
    boiler: list[TableFact] = field(default_factory=list)
    aux: list[TableFact] = field(default_factory=list)
    aggregate: list[TableFact] = field(default_factory=list)
    investment: dict[str, Any] = field(default_factory=dict)
    formulas: list[Formula] = field(default_factory=list)
    narratives: list[dict[str, Any]] = field(default_factory=list)
    checks: list[calc.Check] = field(default_factory=list)

    @property
    def failed(self) -> list[calc.Check]:
        return [c for c in self.checks if not c.ok]

    @property
    def verified(self) -> bool:
        """검산이 하나라도 실패하면 이 문서에서 나온 수치는 인용 대상이 아니다."""
        return bool(self.checks) and not self.failed

    def summary(self) -> dict[str, Any]:
        return {
            "doc_hash": self.doc_hash,
            "filename": self.filename,
            "facility_fields": len([k for k in self.facility if not k.startswith("_")]),
            "pii_dropped": self.pii_dropped,
            "equipment": len(self.equipment),
            "power_rows": len(self.power),
            "measurements": len(self.measurements),
            "boiler_rows": len(self.boiler),
            "aux_rows": len(self.aux),
            "aggregate_rows": len(self.aggregate),
            "formulas": len(self.formulas),
            "narratives": len(self.narratives),
            "checks": len(self.checks),
            "checks_failed": len(self.failed),
            "numeric_verified": self.verified,
            "investment_kwon": self.investment.get("total_kwon"),
            "stated_payback_years": self.investment.get("stated_payback_years"),
        }


def extract(doc: Any, table: UnitTable | None = None) -> Extraction:
    """문서 하나를 통째로 읽는다. 검산은 여기서 전부 끝난다."""
    t = table or load()
    fac, dropped = facility(doc)
    power, power_checks = power_plan(doc, t)
    aux, aux_checks = aux_equipment(doc)
    agg, agg_checks = before_after(doc)
    forms, form_checks = formulas(doc, t)

    ex = Extraction(
        doc_hash=doc.doc_hash,
        filename=doc.filename,
        facility=fac,
        pii_dropped=dropped,
        equipment=equipment(doc),
        power=power,
        measurements=measurements(doc),
        boiler=boiler_plan(doc, t),
        aux=aux,
        aggregate=agg,
        investment=investment(doc),
        formulas=forms,
        narratives=narratives(doc),
        checks=[*prices(doc, t), *power_checks, *aux_checks, *agg_checks, *form_checks],
    )

    # 회수기간은 집계표와 투자비가 모두 있어야 검산할 수 있다.
    total = ex.investment.get("total_kwon")
    stated_payback = ex.investment.get("stated_payback_years")
    saving = _annual_saving_kwon(ex)
    if total and saving:
        ex.checks.append(calc.check(
            "투자비 회수기간", calc.payback_years(total, saving), stated_payback, "년",
            formula="투자비 ÷ 연간 절감금액",
            inputs={"투자비(천원)": total, "연간 절감금액(천원)": saving},
            source="투자 경제성 검토", table=t))
    return ex


def _annual_saving_kwon(ex: Extraction) -> float | None:
    """집계표의 '계 금액' 행에서 연간 절감금액을 얻는다."""
    for f in ex.aggregate:
        if f.fields["group"].replace(" ", "") == "계" and "금액" in f.fields["item"]:
            return f.fields["before"] - f.fields["after"]
    return None
