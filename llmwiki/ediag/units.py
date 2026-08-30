"""단위 환산 테이블 로더 — `data/units.yaml` 이 유일한 원본.

계수를 코드에 적어 넣지 않는다. 상수를 파이썬에 박으면 개정이 왔을 때 grep 으로
찾아 고쳐야 하고, 그 순간 어떤 계산이 옛 계수로 돌았는지 아무도 답할 수 없다.
그래서 계수는 YAML 한 곳에 있고, 계산은 이 모듈을 통해서만 계수를 얻는다.

각 계수는 유효기간을 갖는다. 만료된 계수로 조용히 계산하는 것이 이 도메인에서 가장
흔한 사고라, `expiring()` 이 만료 임박을 목록으로 돌려주고 lint 가 그것을 경고로
올린다(`llmwiki/ediag/lint.py`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

UNITS_PATH = Path(__file__).with_name("data") / "units.yaml"

#: 만료가 이만큼 남았으면 경고한다. 진단 한 건이 착수에서 보고서까지 대략 이 정도다.
EXPIRY_WARN_DAYS = 90


@dataclass(frozen=True)
class Factor:
    code: str
    label: str
    value: float
    unit: str
    valid_from: str = ""
    valid_until: str = ""
    basis: str = ""
    source: str = ""
    dimension: str = ""
    #: 원문이 이 계수를 잘못 적는 흔한 표기. lint 가 이 표기를 찾아 경고한다.
    mislabeled_as: str = ""

    def expires_in(self, today: date | None = None) -> int | None:
        if not self.valid_until:
            return None
        today = today or date.today()
        try:
            end = datetime.strptime(self.valid_until, "%Y-%m-%d").date()
        except ValueError:
            return None
        return (end - today).days

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["expires_in_days"] = self.expires_in()
        return d


class UnitTable:
    """`units.yaml` 한 벌. 계수·단가·순수환산·허용오차를 모두 들고 있다."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = raw
        self.version: str = str(raw.get("version", "0"))
        self.standard: str = str(raw.get("standard", ""))
        self.conversions: dict[str, float] = {
            k: float(v) for k, v in (raw.get("conversions") or {}).items()
        }
        items = [*(raw.get("factors") or []), *(raw.get("prices") or [])]
        self._factors: dict[str, Factor] = {}
        for item in items:
            f = Factor(
                code=str(item["code"]),
                label=str(item.get("label", "")),
                value=float(item["value"]),
                unit=str(item.get("unit", "")),
                valid_from=str(item.get("valid_from", "")),
                valid_until=str(item.get("valid_until", "")),
                basis=str(item.get("basis", "")),
                source=str(item.get("source", "")),
                dimension=str(item.get("dimension", "")),
                mislabeled_as=str(item.get("mislabeled_as", "")),
            )
            if f.code in self._factors:
                raise ValueError(f"단위 테이블에 중복 코드가 있다: {f.code}")
            self._factors[f.code] = f
        tol = raw.get("tolerance") or {}
        self.rel_tolerance = float(tol.get("relative", 0.005))
        self.abs_floor = float(tol.get("absolute_floor", 0.01))

    # --- 조회 ------------------------------------------------------------- #
    def factor(self, code: str) -> Factor:
        try:
            return self._factors[code]
        except KeyError as exc:
            raise KeyError(
                f"단위 테이블에 없는 계수다: {code} — data/units.yaml 을 먼저 고친다"
            ) from exc

    def value(self, code: str) -> float:
        return self.factor(code).value

    def conversion(self, code: str) -> float:
        try:
            return self.conversions[code]
        except KeyError as exc:
            raise KeyError(f"단위 테이블에 없는 환산이다: {code}") from exc

    @property
    def factors(self) -> list[Factor]:
        return list(self._factors.values())

    def expiring(self, *, within_days: int = EXPIRY_WARN_DAYS,
                 today: date | None = None) -> list[Factor]:
        """만료됐거나 만료가 임박한 계수. lint 가 경고로 올린다."""
        out = []
        for f in self._factors.values():
            days = f.expires_in(today)
            if days is not None and days <= within_days:
                out.append(f)
        return sorted(out, key=lambda f: f.expires_in(today) or 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "standard": self.standard,
            "conversions": self.conversions,
            "factors": [f.to_dict() for f in self._factors.values()],
            "tolerance": {"relative": self.rel_tolerance, "absolute_floor": self.abs_floor},
        }


_cache: UnitTable | None = None


def load(path: str | Path | None = None) -> UnitTable:
    """단위 테이블을 읽는다. 기본 경로는 프로세스 안에서 한 번만 읽는다."""
    global _cache
    if path is None:
        if _cache is None:
            _cache = UnitTable(yaml.safe_load(UNITS_PATH.read_text(encoding="utf-8")))
        return _cache
    return UnitTable(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
