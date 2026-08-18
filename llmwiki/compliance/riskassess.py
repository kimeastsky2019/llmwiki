"""AI 위험등급 산정 (STEP 1~5) — 결정론적 룰. **이 파일에 LLM 이 없다.**

증적 기반 통제 판정(`rules.py`)과는 다른 파이프라인이다. 저쪽은 "이 통제가
충족됐나" 를 그래프로 답하고, 여기는 "이 서비스가 몇 등급인가" 를 32개 항목
배점으로 답한다. 둘은 같은 화면에 있지만 섞이지 않는다.

    [입력] 서비스 프로파일 4축
      STEP 1  고영향 판단 → (고영향일 때만) 안전성 대상 판단
      STEP 2  평가세트 결정 (작성 안내 — 점수 필터가 아니다)
      STEP 3  위험 식별 Yes/No → 인식 위험 점수
      STEP 4  완화 방안 + 잔여 평가 → 최종 잔여 위험 점수
      STEP 5  등급 확정 ← 고영향 오버라이드

섞으면 안 되는 두 숫자
--------------------
거버넌스 점수(배점 4·6·8, 가중치 0/0.5/1.0, 구간 25/50/75)는 등급에 반영되고,
기술 임계값(DI 0.8~1.25, PSI 0.25 …)은 위험 식별을 돕는 참고값일 뿐 점수에
들어가지 않는다. 후자가 계산식에 들어가면 규제 근거를 잃는다.

배점은 여기 박아 두지 않는다 — `data/risk_master.yaml` 이 단일 원본이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

MASTER_PATH = Path(__file__).parent / "data" / "risk_master.yaml"

#: 완화 잔여 평가 코드 → 가중치 키. 화면·API 가 어느 쪽으로 보내도 받는다.
_RESIDUAL_ALIASES: dict[str, str] = {
    "○": "full", "O": "full", "full": "full",
    "△": "partial", "partial": "partial",
    "X": "none", "x": "none", "none": "none",
}


@lru_cache(maxsize=1)
def master() -> dict[str, Any]:
    """배점·판정 기준 마스터. 파일이 원본이라 코드에서 고치지 않는다."""
    with MASTER_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def items() -> list[dict[str, Any]]:
    return list(master()["items"])


def points_of(no: int) -> int:
    for item in master()["items"]:
        if int(item["no"]) == no:
            return int(item["points"])
    raise KeyError(f"위험 항목 번호를 찾을 수 없다: {no}")


# --------------------------------------------------------------------------- #
# STEP 1 — 고영향 / 안전성
# --------------------------------------------------------------------------- #
def judge_high_impact(a_checked: list[str], b_checked: list[str]) -> dict[str, Any]:
    """고영향 판단. **배점을 합산하지 않는다.**

    A 가 2개 이상이거나, A 1개 + B 2개 이상이면 고영향이다. 표의 배점은 A 가
    B 보다 무겁다는 표시일 뿐 판정에 쓰이지 않는다. 합산 방식으로 만들면
    'A1 + B1·B2'(합 4, 고영향)와 'B1·B2·B3'(합 3, 비고영향)를 구분할 수 없다.
    """
    valid_a = {g["id"] for g in master()["high_impact"]["groups"]["A"]}
    valid_b = {g["id"] for g in master()["high_impact"]["groups"]["B"]}
    a = sorted(set(a_checked) & valid_a)
    b = sorted(set(b_checked) & valid_b)
    high = len(a) >= 2 or (len(a) == 1 and len(b) >= 2)
    return {
        "high_impact": high,
        "a_count": len(a),
        "b_count": len(b),
        "a_checked": a,
        "b_checked": b,
        "rule": master()["high_impact"]["rule"],
        "reason": (
            f"A그룹 {len(a)}개 · B그룹 {len(b)}개 → "
            + ("고영향" if high else "고영향 아님")
        ),
        "source": master()["high_impact"]["source"],
    }


def judge_safety(
    checked: dict[str, bool] | list[str], *, high_impact: bool
) -> dict[str, Any]:
    """안전성 대상 판단. **AND 조건**이며 고영향일 때만 수행한다."""
    ids = [s["id"] for s in master()["safety"]["items"]]
    if isinstance(checked, list):
        marks = {i: (i in checked) for i in ids}
    else:
        marks = {i: bool(checked.get(i)) for i in ids}

    if not high_impact:
        return {
            "applicable": False,
            "safety_target": None,
            "checked": marks,
            "rule": master()["safety"]["rule"],
            "reason": "고영향 AI 가 아니므로 안전성 대상 판단을 수행하지 않는다",
            "source": master()["safety"]["source"],
        }

    target = all(marks[i] for i in ids)
    return {
        "applicable": True,
        "safety_target": target,
        "checked": marks,
        "rule": master()["safety"]["rule"],
        "reason": (
            ("모든 기준 충족 → 안전성 확보 대상" if target
             else "미충족 항목이 있어 안전성 확보 대상 아님")
            + f" ({', '.join(i for i in ids if marks[i]) or '해당 없음'})"
        ),
        "source": master()["safety"]["source"],
    }


# --------------------------------------------------------------------------- #
# STEP 3~4 — 점수
# --------------------------------------------------------------------------- #
@dataclass
class ItemInput:
    """항목 하나의 입력.

    identified — 위험 식별 Yes/No
    mitigated  — 완화방안 적용 여부. False 면 잔여 평가와 무관하게 가중치 1.0
    residual   — 완화 적용 시 잔여 평가 (○ / △ / X)
    """

    no: int
    identified: bool = False
    mitigated: bool = False
    residual: str = "X"
    note: str = ""


def weight_of(item: ItemInput) -> float:
    """완화 가중치. 미적용(No)이면 1.0 이다 — 0 으로 두면 중대 결함."""
    if not item.mitigated:
        return float(master()["not_mitigated_weight"])
    key = _RESIDUAL_ALIASES.get(str(item.residual).strip(), "none")
    for row in master()["mitigation_weights"]:
        if row["key"] == key:
            return float(row["weight"])
    return float(master()["not_mitigated_weight"])


def score_items(inputs: list[ItemInput]) -> dict[str, Any]:
    """인식 위험 점수와 최종 잔여 위험 점수.

    식별 = No 인 항목은 가중치와 무관하게 0 이다. 반올림하지 않는다 —
    0.5 가중치에 홀수 배점(1, 3)을 곱하면 0.5·1.5 가 나오는데 원본에
    반올림 규정이 없어, 계산은 그대로 두고 표시에서만 자른다.
    """
    by_no = {i.no: i for i in inputs}
    rows: list[dict[str, Any]] = []
    recognized = 0.0
    residual_total = 0.0
    by_lv1: dict[str, dict[str, float]] = {}

    for spec in master()["items"]:
        no = int(spec["no"])
        pts = int(spec["points"])
        given = by_no.get(no, ItemInput(no=no))
        rec = float(pts) if given.identified else 0.0
        w = weight_of(given) if given.identified else 0.0
        res = rec * w
        recognized += rec
        residual_total += res
        bucket = by_lv1.setdefault(spec["lv1"], {"recognized": 0.0, "residual": 0.0,
                                                 "points": 0.0, "count": 0.0})
        bucket["recognized"] += rec
        bucket["residual"] += res
        bucket["points"] += pts
        bucket["count"] += 1
        rows.append({
            "no": no, "lv1": spec["lv1"], "lv2": spec["lv2"], "lv3": spec["lv3"],
            "points": pts, "owner": spec["owner"],
            "identified": given.identified,
            "mitigated": given.mitigated,
            "residual": given.residual if given.mitigated else "",
            "weight": w if given.identified else 0.0,
            "recognized_score": rec,
            "residual_score": res,
            "note": given.note,
        })

    return {
        "rows": rows,
        "recognized_score": recognized,
        "residual_score": residual_total,
        "by_lv1": by_lv1,
        "rounding": master()["rounding"]["mode"],
    }


# --------------------------------------------------------------------------- #
# STEP 5 — 등급
# --------------------------------------------------------------------------- #
def grade_of(score: float) -> dict[str, Any]:
    """점수 → 등급. 경계값은 하단 포함이다 (25 는 중위험, 24 는 저위험)."""
    for band in sorted(master()["grades"], key=lambda g: -int(g["min"])):
        if score >= float(band["min"]):
            return dict(band)
    return dict(min(master()["grades"], key=lambda g: int(g["min"])))


def apply_high_impact_override(band: dict[str, Any], high_impact: bool) -> dict[str, Any]:
    """고영향이면 최소 고위험. **등급을 낮추지는 않는다.**

    별첨04 등급 시트에는 안 나오고 규정에만 있어서 빠뜨리기 쉬운 규칙이다.
    점수가 0 이어도 고영향이면 고위험이어야 한다.
    """
    cfg = master()["high_impact_override"]
    if not (cfg.get("enabled") and high_impact):
        return {**band, "override_applied": False}
    floor = next(g for g in master()["grades"] if g["key"] == cfg["floor"])
    if int(band["rank"]) >= int(floor["rank"]):
        return {**band, "override_applied": False}
    return {**floor, "override_applied": True, "override_from": band["key"],
            "override_source": cfg["source"]}


# --------------------------------------------------------------------------- #
# 전체 파이프라인
# --------------------------------------------------------------------------- #
@dataclass
class RiskInput:
    service_uuid: str = ""
    service_name: str = ""
    high_impact_a: list[str] = field(default_factory=list)
    high_impact_b: list[str] = field(default_factory=list)
    safety: dict[str, bool] = field(default_factory=dict)
    safety_stage: str = ""
    profile: dict[str, str] = field(default_factory=dict)
    items: list[ItemInput] = field(default_factory=list)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "RiskInput":
        raw_items = payload.get("items") or []
        return RiskInput(
            service_uuid=str(payload.get("service_uuid", "")),
            service_name=str(payload.get("service_name", "")),
            high_impact_a=list(payload.get("high_impact_a") or []),
            high_impact_b=list(payload.get("high_impact_b") or []),
            safety=dict(payload.get("safety") or {}),
            safety_stage=str(payload.get("safety_stage", "")),
            profile=dict(payload.get("profile") or {}),
            items=[
                ItemInput(
                    no=int(r.get("no")),
                    identified=bool(r.get("identified")),
                    mitigated=bool(r.get("mitigated")),
                    residual=str(r.get("residual", "X")),
                    note=str(r.get("note", "")),
                )
                for r in raw_items
                if r.get("no") is not None
            ],
        )


def assess(payload: RiskInput | dict[str, Any], *, assessed_at: str = "") -> dict[str, Any]:
    """STEP 1~5 를 한 번에 돌린다. 같은 입력이면 항상 같은 답이 나온다."""
    data = payload if isinstance(payload, RiskInput) else RiskInput.from_dict(payload)

    step1 = judge_high_impact(data.high_impact_a, data.high_impact_b)
    safety = judge_safety(data.safety, high_impact=step1["high_impact"])
    scored = score_items(data.items)
    computed = grade_of(scored["residual_score"])
    final = apply_high_impact_override(computed, step1["high_impact"])

    return {
        "service_uuid": data.service_uuid,
        "service_name": data.service_name,
        "profile": data.profile,
        "step1_high_impact": step1,
        "step1_safety": {**safety, "stage": data.safety_stage},
        "step2_evaluation_set": {
            **master()["evaluation_set"],
            "axes": master()["profile_axes"],
            "selected": data.profile,
        },
        "step3_recognized_score": scored["recognized_score"],
        "step4_residual_score": scored["residual_score"],
        "rows": scored["rows"],
        "by_lv1": scored["by_lv1"],
        "computed_grade": computed,
        "final_grade": final,
        # 판정을 재현하려면 어느 기준으로 쟀는지가 함께 있어야 한다.
        "versions": {
            "master": master()["version"],
            **master()["standard"],
        },
        "assessed_at": assessed_at,
        # 이 화면의 숫자는 전부 룰이 계산한 것이다. LLM 서술과 섞이지 않는다.
        "derivation": "rule",
    }


# --------------------------------------------------------------------------- #
# 배점 무결성 — 마스터가 손상되면 즉시 알아야 한다
# --------------------------------------------------------------------------- #
INVARIANTS: dict[str, tuple[int, int]] = {
    "합법성 원칙": (6, 20),
    "신뢰성 원칙": (11, 30),
    "신의성실의 원칙": (4, 20),
    "보안성 원칙": (11, 30),
}


def check_master() -> list[str]:
    """불변식 위반 목록. 비어 있으면 정상."""
    problems: list[str] = []
    rows = master()["items"]
    if len(rows) != 32:
        problems.append(f"항목 수가 32 가 아니다: {len(rows)}")
    total = sum(int(r["points"]) for r in rows)
    if total != 100:
        problems.append(f"총 배점이 100 이 아니다: {total}")
    for lv1, (count, points) in INVARIANTS.items():
        got = [r for r in rows if r["lv1"] == lv1]
        if len(got) != count:
            problems.append(f"{lv1} 문항 수 {len(got)} != {count}")
        got_points = sum(int(r["points"]) for r in got)
        if got_points != points:
            problems.append(f"{lv1} 배점 {got_points} != {points}")
    numbers = [int(r["no"]) for r in rows]
    if numbers != list(range(1, len(rows) + 1)):
        problems.append("항목 번호가 1..N 연속이 아니다")
    return problems
