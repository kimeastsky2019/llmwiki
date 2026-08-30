"""AI 위험등급 산정 — 검증 명세서 §5 골든 테스트 케이스.

명세서(planning/규제준수_자동평가_검증명세서_v1.0.md)의 T-01~T-06 을 그대로
옮겼다. 이 파일이 통과하지 않으면 규제 근거를 잃은 구현이다.

중대 결함 기준(명세서 §8)에 해당하는 것부터 고정한다:
  고영향을 점수 합산으로 구현 · 안전성을 OR 로 구현 · 고영향 오버라이드 누락 ·
  기술 임계값이 등급 점수에 반영 · 배점 총합 ≠ 100 · 완화 미적용 가중치 ≠ 1.0
"""

from __future__ import annotations

import pytest

from llmwiki.compliance import riskassess as ra
from llmwiki.compliance.riskassess import ItemInput


# --------------------------------------------------------------------------- #
# T-06 · 배점 무결성 (V-A1, V-A2)
# --------------------------------------------------------------------------- #
def test_master_invariants_hold():
    assert ra.check_master() == []


def test_item_count_and_total_points():
    rows = ra.items()
    assert len(rows) == 32
    assert sum(int(r["points"]) for r in rows) == 100


@pytest.mark.parametrize(
    "lv1,count,points",
    [("합법성 원칙", 6, 20), ("신뢰성 원칙", 11, 30),
     ("신의성실의 원칙", 4, 20), ("보안성 원칙", 11, 30)],
)
def test_section_subtotals(lv1, count, points):
    rows = [r for r in ra.items() if r["lv1"] == lv1]
    assert len(rows) == count
    assert sum(int(r["points"]) for r in rows) == points


def test_three_level_hierarchy_is_kept():
    for r in ra.items():
        assert r["lv1"] and r["lv2"] and r["lv3"]
        assert r["owner"]


@pytest.mark.parametrize("no,points", [(1, 4), (10, 6), (13, 1), (27, 8), (28, 3), (32, 2)])
def test_spot_check_points_against_spec(no, points):
    assert ra.points_of(no) == points


# --------------------------------------------------------------------------- #
# T-01 · 고영향 판정 — 조합 규칙 (V-B1, 중대)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "case,a,b,expected",
    [
        ("T-01-1", ["A1", "A2"], [], True),
        ("T-01-2", ["A1"], ["B1", "B2"], True),
        ("T-01-3", [], ["B1", "B2", "B3"], False),
        ("T-01-4", ["A1"], ["B1"], False),
        ("T-01-5", ["A1"], [], False),
        ("T-01-6", ["A1", "A2", "A3"], ["B1", "B2", "B3"], True),
    ],
)
def test_high_impact_combination_rule(case, a, b, expected):
    assert ra.judge_high_impact(a, b)["high_impact"] is expected, case


def test_high_impact_is_not_a_point_sum():
    """배점 합이 같거나 역전돼도 조합 규칙이 이긴다.

    A1+B1·B2 는 합 4 로 고영향, B1·B2·B3 는 합 3 인데 비고영향이다.
    합산 구현이면 이 둘 중 하나는 반드시 틀린다.
    """
    yes = ra.judge_high_impact(["A1"], ["B1", "B2"])
    no = ra.judge_high_impact([], ["B1", "B2", "B3"])
    assert yes["high_impact"] is True
    assert no["high_impact"] is False


def test_unknown_checklist_ids_are_ignored():
    out = ra.judge_high_impact(["A1", "A9", "잡음"], ["B1", "B7"])
    assert out["a_count"] == 1 and out["b_count"] == 1
    assert out["high_impact"] is False


# --------------------------------------------------------------------------- #
# T-02 · 안전성 판정 — AND (V-B3, V-B4, 중대)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "case,s1,s2,s3,expected",
    [
        ("T-02-1", True, True, True, True),
        ("T-02-2", True, True, False, False),
        ("T-02-3", False, True, True, False),
        ("T-02-4", False, False, False, False),
    ],
)
def test_safety_is_and(case, s1, s2, s3, expected):
    out = ra.judge_safety({"S1": s1, "S2": s2, "S3": s3}, high_impact=True)
    assert out["applicable"] is True
    assert out["safety_target"] is expected, case


def test_safety_is_skipped_when_not_high_impact():
    """T-02-5 — 고영향이 아니면 판정 자체를 수행하지 않는다."""
    out = ra.judge_safety({"S1": True, "S2": True, "S3": True}, high_impact=False)
    assert out["applicable"] is False
    assert out["safety_target"] is None


def test_safety_flops_threshold_text_is_10_to_the_26():
    s1 = next(s for s in ra.master()["safety"]["items"] if s["id"] == "S1")
    assert "10^26" in s1["text"]


# --------------------------------------------------------------------------- #
# T-03 · 점수 계산 (V-C1~V-C5)
# --------------------------------------------------------------------------- #
def _one(no, identified, mitigated, residual="X"):
    return ra.score_items([ItemInput(no=no, identified=identified,
                                     mitigated=mitigated, residual=residual)])


@pytest.mark.parametrize(
    "case,no,identified,mitigated,residual,expected",
    [
        ("T-03-1", 2, True, True, "△", 2.0),
        ("T-03-2", 2, True, False, "X", 4.0),
        ("T-03-3", 2, True, True, "○", 0.0),
        ("T-03-4", 2, False, True, "X", 0.0),
        ("T-03-5", 27, True, True, "X", 8.0),
        ("T-03-6", 13, True, True, "△", 0.5),
    ],
)
def test_item_score(case, no, identified, mitigated, residual, expected):
    got = _one(no, identified, mitigated, residual)["residual_score"]
    assert got == pytest.approx(expected), case


def test_all_identified_and_unmitigated_is_100():
    """T-03-7 — 전 항목 식별 Yes, 전부 완화 No."""
    ins = [ItemInput(no=int(r["no"]), identified=True, mitigated=False)
           for r in ra.items()]
    out = ra.score_items(ins)
    assert out["recognized_score"] == pytest.approx(100.0)
    assert out["residual_score"] == pytest.approx(100.0)


def test_nothing_identified_is_zero():
    """T-03-8."""
    out = ra.score_items([ItemInput(no=int(r["no"])) for r in ra.items()])
    assert out["recognized_score"] == 0.0
    assert out["residual_score"] == 0.0


def test_not_mitigated_weight_is_one_not_zero():
    """V-C2 (중대) — 완화방안 미적용을 0 으로 처리하면 위험이 사라진다."""
    assert ra.weight_of(ItemInput(no=1, identified=True, mitigated=False)) == 1.0


def test_identified_no_is_zero_regardless_of_residual():
    """V-C3 — 식별 No 면 잔여 평가가 무엇이든 0."""
    for residual in ("○", "△", "X"):
        out = _one(2, False, True, residual)
        assert out["residual_score"] == 0.0


def test_section_subtotals_match_the_total():
    """V-C6 — 부문 소계 합 == 전체 합."""
    ins = [ItemInput(no=int(r["no"]), identified=True, mitigated=True, residual="△")
           for r in ra.items()]
    out = ra.score_items(ins)
    assert sum(v["residual"] for v in out["by_lv1"].values()) == pytest.approx(
        out["residual_score"]
    )


def test_rounding_rule_is_declared_and_exact():
    """V-C5 — 원본에 반올림 규정이 없다. 계산은 그대로 두는 것을 고정한다."""
    assert ra.master()["rounding"]["mode"] == "none"
    # 1점 항목 × 0.5 = 0.5 가 반올림되어 0 이나 1 이 되면 안 된다
    assert _one(13, True, True, "△")["residual_score"] == 0.5
    # 3점 항목 × 0.5 = 1.5
    assert _one(28, True, True, "△")["residual_score"] == 1.5


# --------------------------------------------------------------------------- #
# T-04 · 등급 경계 (V-D1, V-D2)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "case,score,expected",
    [
        ("T-04-1", 0, "저위험 서비스"),
        ("T-04-2", 24, "저위험 서비스"),
        ("T-04-3", 25, "중위험 서비스"),
        ("T-04-4", 49, "중위험 서비스"),
        ("T-04-5", 50, "고위험 서비스"),
        ("T-04-6", 74, "고위험 서비스"),
        ("T-04-7", 75, "허용불가 서비스"),
        ("T-04-8", 100, "허용불가 서비스"),
    ],
)
def test_grade_bands_are_lower_inclusive(case, score, expected):
    assert ra.grade_of(score)["label"] == expected, case


# --------------------------------------------------------------------------- #
# T-05 · 고영향 오버라이드 (V-D3, V-D4, 중대) ★
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "case,high,score,expected,overridden",
    [
        ("T-05-1", True, 0, "고위험 서비스", True),
        ("T-05-2", True, 30, "고위험 서비스", True),
        ("T-05-3", True, 60, "고위험 서비스", False),
        ("T-05-4", True, 80, "허용불가 서비스", False),
        ("T-05-5", False, 10, "저위험 서비스", False),
    ],
)
def test_high_impact_override(case, high, score, expected, overridden):
    band = ra.grade_of(score)
    final = ra.apply_high_impact_override(band, high)
    assert final["label"] == expected, case
    assert final["override_applied"] is overridden, case


def test_override_never_lowers_the_grade():
    """T-05-4 — 허용불가를 고위험으로 끌어내리면 안 된다."""
    final = ra.apply_high_impact_override(ra.grade_of(100), True)
    assert final["label"] == "허용불가 서비스"


# --------------------------------------------------------------------------- #
# 파이프라인 전체 · 기술 임계값 분리 (V-F1, 중대)
# --------------------------------------------------------------------------- #
def test_pipeline_runs_end_to_end():
    out = ra.assess({
        "service_uuid": "svc-credit-scoring",
        "high_impact_a": ["A1"], "high_impact_b": ["B1", "B2"],
        "safety": {"S1": True, "S2": True, "S3": False},
        "profile": {"user_scope": "대고객 서비스"},
        "items": [
            {"no": 2, "identified": True, "mitigated": True, "residual": "△"},
            {"no": 27, "identified": True, "mitigated": False},
        ],
    })
    assert out["step1_high_impact"]["high_impact"] is True
    assert out["step1_safety"]["applicable"] is True
    assert out["step1_safety"]["safety_target"] is False
    assert out["step3_recognized_score"] == pytest.approx(12.0)   # 4 + 8
    assert out["step4_residual_score"] == pytest.approx(10.0)     # 2 + 8
    # 10점이면 저위험이지만 고영향이라 고위험으로 올라간다
    assert out["computed_grade"]["label"] == "저위험 서비스"
    assert out["final_grade"]["label"] == "고위험 서비스"
    assert out["final_grade"]["override_applied"] is True
    assert len(out["rows"]) == 32


def test_zero_score_high_impact_is_still_high_grade():
    out = ra.assess({"high_impact_a": ["A1", "A2"], "items": []})
    assert out["step4_residual_score"] == 0.0
    assert out["final_grade"]["label"] == "고위험 서비스"


def test_technical_thresholds_are_declared_unscored():
    """V-F1 — 기술 임계값은 참고값이다. 점수 계산에 들어가면 중대 결함."""
    tech = ra.master()["technical_thresholds"]
    assert tech["scored"] is False
    # 엔진이 임계값을 아예 읽지 않는다는 것을 값 변조로 확인한다
    out_before = ra.assess({"items": [{"no": 14, "identified": True, "mitigated": False}]})
    saved = tech["entries"]
    try:
        tech["entries"] = []
        out_after = ra.assess({"items": [{"no": 14, "identified": True, "mitigated": False}]})
    finally:
        tech["entries"] = saved
    assert out_before["step4_residual_score"] == out_after["step4_residual_score"]


def test_result_records_the_standard_versions():
    """V-G4 — 언제·무슨 기준으로 쟀는지가 결과에 남아야 재현된다."""
    out = ra.assess({"items": []}, assessed_at="2026-08-18T00:00:00+00:00")
    assert out["versions"]["master"]
    assert "RMF" in out["versions"]["rmf"] or "위험관리" in out["versions"]["rmf"]
    assert out["assessed_at"] == "2026-08-18T00:00:00+00:00"
    assert out["derivation"] == "rule"


def test_evaluation_set_mapping_is_declared_undefined():
    """§7-C — 4축 매핑은 원본 미확정이다. 추측으로 채우지 않았음을 고정한다."""
    assert ra.master()["evaluation_set"]["mapping_defined"] is False


def test_axes_match_the_spec():
    keys = [a["key"] for a in ra.master()["profile_axes"]]
    assert keys == ["user_scope", "output_kind", "decision_impact", "data_sensitivity"]
    opts = {a["key"]: a["options"] for a in ra.master()["profile_axes"]}
    assert opts["user_scope"] == ["대고객 서비스", "임직원 서비스"]
    assert len(opts["output_kind"]) == 3 and len(opts["decision_impact"]) == 3
    assert opts["data_sensitivity"] == ["비개인정보", "개인정보", "민감·신용정보"]
