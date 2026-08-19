"""수치 계산 엔진 — 설계 원칙 P2 의 집행 장치.

    **숫자는 LLM 이 생성하지 않는다.** 수치는 원문 스팬 인용, 계산은 파이썬 코드.

에너지 진단에서 수치가 틀리면 바로 사업 리스크다. 절감량 하나가 틀리면 회수기간이
틀리고, 회수기간이 틀리면 투자 판단이 틀린다. 그래서 이 모듈의 함수만이 양을 만들고,
LLM 은 **원문에서 입력값을 정확히 뽑는 역할**만 맡는다.

두 가지 일을 한다.

1. **계산** — 연간 사용량·toe 환산·배출량·금액·절감량·회수기간.
   계수는 하나도 여기 적혀 있지 않다. 전부 `data/units.yaml` 에서 온다.
2. **검산** — 보고서에 적힌 값을 같은 입력으로 다시 계산해 대조한다.
   불일치는 `Check.ok=False` 로 남고, 그 값을 인용하는 위키 페이지는
   `numeric_verified: false` 가 되어 서비스 응답에서 인용되지 않는다.

검산이 이 모듈의 실질이다. 계산만 하면 "우리 계산은 이렇다" 로 끝나지만, 검산을 하면
**원문이 틀렸다는 것**을 잡아낸다. 실제로 비이테크 진단서(2026-04)에서 이 검산이
집계표의 전기 온실가스 증감(-2,095.16 tCO2eq)이 실제 차이(-1,756.86)와 다르다는 것을
찾아냈다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .units import UnitTable, load


# --------------------------------------------------------------------------- #
# 검산 결과
# --------------------------------------------------------------------------- #
@dataclass
class Check:
    """원문에 적힌 값 하나에 대한 검산 결과."""

    label: str
    stated: float | None
    computed: float
    unit: str
    formula: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    ok: bool = True
    #: 상대 오차. stated 가 없으면 None (검산 대상이 아니라 계산 결과다)
    delta_pct: float | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "stated": self.stated,
            "computed": round(self.computed, 4),
            "unit": self.unit,
            "formula": self.formula,
            "inputs": self.inputs,
            "source": self.source,
            "ok": self.ok,
            "delta_pct": None if self.delta_pct is None else round(self.delta_pct, 4),
            "note": self.note,
        }


def check(label: str, computed: float, stated: float | None, unit: str, *,
          formula: str = "", inputs: dict[str, Any] | None = None, source: str = "",
          table: UnitTable | None = None) -> Check:
    """계산값과 원문값을 대조한다.

    보고서는 중간값을 반올림해 적는다(913.57 toe). 허용오차를 0 으로 두면 전부
    불일치가 되고, 크게 두면 진짜 오류를 놓친다. 허용오차도 코드가 아니라
    `units.yaml` 에 있다 — 조정 근거가 한 곳에 남아야 한다.
    """
    t = table or load()
    c = Check(label=label, stated=stated, computed=computed, unit=unit,
              formula=formula, inputs=dict(inputs or {}), source=source)
    if stated is None:
        c.delta_pct = None
        c.ok = True
        c.note = "원문에 대응값이 없다 — 계산으로만 제시한다"
        return c
    scale = max(abs(stated), abs(computed), t.abs_floor)
    c.delta_pct = abs(computed - stated) / scale
    # 원문이 적은 자릿수까지 일치하면 통과다. 보고서는 4.572 를 `4.6(년)` 으로 적는데,
    # 상대오차만 보면 0.61% 라 실패로 잡힌다 — 그건 오류가 아니라 표기다.
    c.ok = c.delta_pct <= t.rel_tolerance or _same_at_printed_precision(stated, computed)
    if not c.ok:
        c.note = f"원문 {stated:,.2f} vs 재계산 {computed:,.2f} ({c.delta_pct * 100:.2f}% 차이)"
    return c


def _printed_decimals(value: float) -> int:
    """원문이 몇 자리까지 적었는지. `4.6` 은 1자리, `2,664,576` 은 0자리."""
    text = repr(float(value))
    if "e" in text or "E" in text:
        return 6
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def _same_at_printed_precision(stated: float, computed: float) -> bool:
    d = _printed_decimals(stated)
    return round(computed, d) == round(stated, d)


# --------------------------------------------------------------------------- #
# 전력
# --------------------------------------------------------------------------- #
def annual_kwh(rated_kw: float, hours_per_year: float, load_ratio: float,
               count: int = 1) -> float:
    """연간 전력량(kWh/y) = 대수 × 정격(또는 실측)전력 × 연간가동시간 × 부하율."""
    return count * rated_kw * hours_per_year * load_ratio


def operating_hours(hours_per_day: float, days_per_year: float) -> float:
    return hours_per_day * days_per_year


def toe_from_kwh(kwh: float, table: UnitTable | None = None) -> float:
    t = table or load()
    return (kwh / t.conversion("kwh_per_mwh")) * t.value("elec.toe_per_mwh")


def tco2eq_from_kwh(kwh: float, table: UnitTable | None = None) -> float:
    t = table or load()
    return (kwh / t.conversion("kwh_per_mwh")) * t.value("elec.tco2eq_per_mwh")


def elec_cost_kwon(kwh: float, table: UnitTable | None = None) -> float:
    """전기요금(천원). 진단 보고서의 집계 단위가 천원이라 여기 맞춘다."""
    t = table or load()
    return kwh * t.value("price.elec_won_per_kwh") / t.conversion("won_per_kwon")


# --------------------------------------------------------------------------- #
# 연료 (LPG)
# --------------------------------------------------------------------------- #
def annual_fuel_kg(rate_kg_h: float, hours_per_day: float, days_per_year: float,
                   load_ratio: float) -> float:
    return rate_kg_h * hours_per_day * days_per_year * load_ratio


def toe_from_lpg_kg(kg: float, table: UnitTable | None = None) -> float:
    t = table or load()
    return (kg / t.conversion("kg_per_ton")) * t.value("lpg.toe_per_ton")


def tco2eq_from_lpg_kg(kg: float, table: UnitTable | None = None) -> float:
    """LPG 배출량. 분모는 **LPG 1톤**이지 toe 가 아니다.

    원문이 `2.918(tCO2eq/toe)` 로 적었더라도 toe 에 곱하면 안 된다 — 그러면
    배출량이 20% 부풀려진다. 라벨 오기는 lint 의 `unit.label_mismatch` 가 잡는다.
    """
    t = table or load()
    return (kg / t.conversion("kg_per_ton")) * t.value("lpg.tco2eq_per_ton")


def lpg_cost_kwon(kg: float, table: UnitTable | None = None) -> float:
    t = table or load()
    return kg * t.value("price.lpg_won_per_kg") / t.conversion("won_per_kwon")


def boiler_fuel_rate_kg_h(steam_ton_h: float, load_ratio: float, efficiency: float,
                          table: UnitTable | None = None) -> float:
    """보일러 시간당 연료 소비량(kg/h).

        Qout = 증기량 × 부하율 × 증기 1톤당 열량
        Qin  = Qout ÷ 효율
        F    = Qin ÷ 저위발열량

    효율이 0 이하면 계산 자체가 성립하지 않는다 — 조용히 0 을 돌려주지 않는다.
    """
    if efficiency <= 0:
        raise ValueError("보일러 효율은 0보다 커야 한다")
    t = table or load()
    q_out = steam_ton_h * load_ratio * t.value("steam.kcal_per_ton")
    q_in = q_out / efficiency
    return q_in / t.value("lpg.lhv_kcal_per_kg")


# --------------------------------------------------------------------------- #
# 절감 · 경제성
# --------------------------------------------------------------------------- #
@dataclass
class Savings:
    before: float
    after: float
    unit: str
    label: str = ""

    @property
    def saved(self) -> float:
        return self.before - self.after

    @property
    def rate(self) -> float:
        """절감률. 사업전이 0 이면 비율이 정의되지 않는다 — 0 으로 얼버무리지 않는다."""
        if self.before == 0:
            return float("nan")
        return self.saved / self.before

    def to_dict(self) -> dict[str, Any]:
        rate = self.rate
        return {
            "label": self.label,
            "unit": self.unit,
            "before": round(self.before, 4),
            "after": round(self.after, 4),
            "saved": round(self.saved, 4),
            "rate_pct": None if rate != rate else round(rate * 100, 2),  # NaN 체크
        }


def savings(before: float, after: float, unit: str, label: str = "") -> Savings:
    return Savings(before=before, after=after, unit=unit, label=label)


def payback_years(investment_kwon: float, annual_saving_kwon: float) -> float:
    """간이 자본회수법. 절감액이 0 이하면 회수되지 않는다 — 무한대를 돌려준다.

    0 으로 나눠 예외를 던지거나 0 을 돌려주면 화면에 '회수기간 0년' 이 뜬다.
    그것이 이 도메인에서 가장 위험한 표시다.
    """
    if annual_saving_kwon <= 0:
        return float("inf")
    return investment_kwon / annual_saving_kwon


def energy_intensity(annual_toe: float, throughput: float, basis: str = "ton") -> float:
    """에너지 원단위 = 연간 에너지사용량(toe) ÷ 처리량. 업종마다 분모가 다르다."""
    if throughput <= 0:
        raise ValueError("원단위 분모(처리량)는 0보다 커야 한다")
    return annual_toe / throughput
