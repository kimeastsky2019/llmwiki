"""sLM 조언자 — 조언은 하되 판정은 하지 않는다.

여기서 고정하는 것은 셋이다.
  1) 응답에 판정이 들어갈 자리가 없다 (verdict/identified/score)
  2) 사내 모델을 먼저 쓴다
  3) 외부 API 로는 **명시 허용 없이 넘어가지 않는다** — 프롬프트에 운영 소스의
     테이블명·URL 이 들어가므로 조용한 폴백은 자료 유출이다
"""

from __future__ import annotations

import json

import pytest

from llmwiki.compliance import advise as advisor
from llmwiki.compliance import riskassess
from llmwiki.config import Config


def _cfg(providers: dict, default: str = "ollama") -> Config:
    return Config(raw={"llm": {"provider": default, **providers}}, root=__import__("pathlib").Path("."))


class FakeProvider:
    """호출되면 기록을 남기는 가짜 공급자."""

    calls: list[tuple[str, str, str]] = []

    def __init__(self, name: str, payload: dict | str | None = None, fail: bool = False):
        self.name = name
        self.payload = payload
        self.fail = fail

    def complete(self, system: str, prompt: str) -> str:
        FakeProvider.calls.append((self.name, system, prompt))
        if self.fail:
            raise RuntimeError(f"{self.name} 죽음")
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload or {
            "relevance": "high",
            "summary": "고객 식별정보를 읽는 경로가 있어 확인이 필요하다.",
            "checkpoints": ["동의 범위 확인", "가명처리 여부 확인"],
            "evidence": ["개인정보 처리방침", "DB 접근 권한 대장"],
            "mitigations": ["컬럼 마스킹", "접근 로그 보존"],
        }, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _reset():
    FakeProvider.calls = []
    yield
    FakeProvider.calls = []


def _patch(monkeypatch, ready: dict[str, bool], providers: dict[str, FakeProvider]):
    class R:
        def __init__(self, ok): self.ok = ok; self.reason = "" if ok else "준비 안 됨"
        def to_dict(self): return {"ok": self.ok, "reason": self.reason, "hint": "", "detail": ""}
    monkeypatch.setattr(advisor, "check_provider", lambda name, opts: R(ready.get(name, False)))
    monkeypatch.setattr(advisor, "get_provider", lambda name, opts: providers[name])


# --------------------------------------------------------------------------- #
# 판정하지 않는다
# --------------------------------------------------------------------------- #
def test_response_has_no_place_for_a_verdict():
    out = advisor.Advice(item_no=1, stage="identify").to_dict()
    for forbidden in ("verdict", "identified", "score", "grade", "residual", "weight"):
        assert forbidden not in out, f"조언 응답에 판정 자리가 있으면 안 된다: {forbidden}"
    assert out["derivation"] == "llm"


def test_system_prompt_forbids_judging():
    system, _ = advisor.build_prompt(
        1, stage="identify", service="여신심사", profile={}, facts={}
    )
    assert "판정하지 마라" in system
    assert "지어내지 마라" in system
    # 판정 필드를 아예 요구하지 않는다
    assert "verdict" not in system


def test_relevance_is_not_a_verdict(monkeypatch):
    _patch(monkeypatch, {"ollama": True}, {"ollama": FakeProvider("ollama")})
    out = advisor.advise(_cfg({"ollama": {"model": "m"}}), item_no=5)
    assert out.relevance in ("high", "medium", "low", "unclear")
    assert not hasattr(out, "verdict")


def test_unknown_relevance_falls_back_to_unclear(monkeypatch):
    fake = FakeProvider("ollama", {"relevance": "위험함", "summary": "x"})
    _patch(monkeypatch, {"ollama": True}, {"ollama": fake})
    out = advisor.advise(_cfg({"ollama": {"model": "m"}}), item_no=5)
    assert out.relevance == "unclear"


# --------------------------------------------------------------------------- #
# 사내 우선 · 외부는 명시 허용 필요
# --------------------------------------------------------------------------- #
def test_local_provider_is_tried_first(monkeypatch):
    local, external = FakeProvider("ollama"), FakeProvider("grok")
    _patch(monkeypatch, {"ollama": True, "grok": True},
           {"ollama": local, "grok": external})
    out = advisor.advise(
        _cfg({"ollama": {"model": "m"}, "grok": {"model": "g"}}),
        item_no=4, allow_external=True,
    )
    assert out.provider == "ollama"
    assert out.local is True
    assert out.fell_back is False
    assert [c[0] for c in FakeProvider.calls] == ["ollama"]


def test_external_is_not_used_without_permission(monkeypatch):
    """사내 모델이 죽어도 허용 안 하면 외부로 넘기지 않는다."""
    local, external = FakeProvider("ollama", fail=True), FakeProvider("grok")
    _patch(monkeypatch, {"ollama": True, "grok": True},
           {"ollama": local, "grok": external})
    out = advisor.advise(
        _cfg({"ollama": {"model": "m"}, "grok": {"model": "g"}}),
        item_no=4, allow_external=False,
    )
    assert out.provider == ""
    assert out.error
    # 외부 공급자는 호출조차 되지 않아야 한다 — 프롬프트가 나가면 안 된다
    assert "grok" not in [c[0] for c in FakeProvider.calls]


def test_external_is_used_when_permitted_and_flagged(monkeypatch):
    local, external = FakeProvider("ollama", fail=True), FakeProvider("grok")
    _patch(monkeypatch, {"ollama": True, "grok": True},
           {"ollama": local, "grok": external})
    out = advisor.advise(
        _cfg({"ollama": {"model": "m"}, "grok": {"model": "g"}}),
        item_no=4, allow_external=True,
    )
    assert out.provider == "grok"
    assert out.local is False
    # 넘어갔다는 사실이 결과에 남아야 화면이 알릴 수 있다
    assert out.fell_back is True
    assert out.tried and out.tried[0]["provider"] == "ollama"


def test_chain_without_permission_has_no_external():
    cfg = _cfg({"ollama": {"model": "m"}, "grok": {"model": "g"}, "claude": {"model": "c"}})
    assert advisor.provider_chain(cfg, allow_external=False) == ["ollama"]
    chain = advisor.provider_chain(cfg, allow_external=True)
    assert chain[0] == "ollama" and set(chain[1:]) == {"grok", "claude"}


def test_no_provider_at_all_is_reported_not_raised():
    cfg = _cfg({"grok": {"model": "g"}}, default="grok")
    out = advisor.advise(cfg, item_no=1, allow_external=False)
    assert out.error and "외부 API 허용" in out.error


def test_provider_failure_never_raises(monkeypatch):
    """LLM 이 죽었다고 평가 자체가 막히면 안 된다."""
    _patch(monkeypatch, {"ollama": True}, {"ollama": FakeProvider("ollama", fail=True)})
    out = advisor.advise(_cfg({"ollama": {"model": "m"}}), item_no=1)
    assert out.error
    assert out.tried[0]["provider"] == "ollama"


def test_unparseable_response_is_reported(monkeypatch):
    _patch(monkeypatch, {"ollama": True}, {"ollama": FakeProvider("ollama", "안녕하세요")})
    out = advisor.advise(_cfg({"ollama": {"model": "m"}}), item_no=1)
    assert out.error
    assert "JSON" in out.tried[0]["error"]


# --------------------------------------------------------------------------- #
# 프롬프트에 실리는 사실
# --------------------------------------------------------------------------- #
def test_prompt_carries_code_facts():
    _, user = advisor.build_prompt(
        5, stage="identify", service="여신심사 스코어링",
        profile={"data_sensitivity": "민감·신용정보"},
        facts={"programs": ["내 계좌 조회"], "tables": ["TB_CUST", "TB_ACCT"],
               "crud": {"TB_CUST": ["R"]}, "urls": ["/channel/acct/myAccounts.json"],
               "layers": ["채널계"]},
    )
    assert "TB_CUST" in user and "채널계" in user
    assert "민감·신용정보" in user
    assert "여신심사 스코어링" in user


def test_prompt_says_so_when_there_are_no_code_facts():
    _, user = advisor.build_prompt(5, stage="identify", service="x", profile={}, facts={})
    assert "코드 근거 없이" in user


def test_mitigate_stage_asks_for_mitigations_only_then():
    sys_id, _ = advisor.build_prompt(2, stage="identify", service="x", profile={}, facts={})
    sys_mit, user_mit = advisor.build_prompt(2, stage="mitigate", service="x",
                                             profile={}, facts={})
    assert "mitigations" not in sys_id
    assert "mitigations" in sys_mit
    assert "완화 방안을 검토하는 단계" in user_mit


def test_mitigations_are_dropped_on_identify_stage(monkeypatch):
    _patch(monkeypatch, {"ollama": True}, {"ollama": FakeProvider("ollama")})
    out = advisor.advise(_cfg({"ollama": {"model": "m"}}), item_no=2, stage="identify")
    assert out.mitigations == []


def test_prompt_uses_the_master_item_spec():
    _, user = advisor.build_prompt(27, stage="identify", service="x", profile={}, facts={})
    spec = next(i for i in riskassess.items() if i["no"] == 27)
    assert spec["lv3"] in user
    assert f"{spec['points']}점" in user


def test_unknown_item_number_raises():
    with pytest.raises(KeyError):
        advisor.build_prompt(999, stage="identify", service="x", profile={}, facts={})
