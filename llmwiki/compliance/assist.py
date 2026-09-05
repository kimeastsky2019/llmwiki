"""기획 도우미 — 사내 sLM 과 함께 서비스를 기획한다.

`advise.py` 와 목적이 다르다. 저쪽은 위험 항목 **하나**에 대한 구조화된 조언이고,
여기는 기획자가 자유롭게 묻는 자리다. 회의에서 나온 이 말이 근거다 —

  "이 폼 자체가 개발이나 기획자들이나 사업 기획하거나 이런 사람들 리마인드
   시켜주는 거거든요. 서비스 기획하는 이런 부분들 해야 돼 개인 정보 있을 때
   이런 부분들도 있어"

지키는 선은 `advise.py` 와 같다.

1. **모델은 판정하지 않는다.** 등급·점수·Yes/No 를 말하지 않게 하고, 응답에
   그런 자리를 만들지도 않는다. 물으면 "그건 룰이 계산합니다" 로 돌린다.
2. **사내 모델이 먼저다.** 기획 내용에는 아직 공개되지 않은 서비스 계획이
   들어간다. 외부 API 로 보내는 것은 요청자가 명시적으로 허용했을 때만이다.
3. **아는 것만 말한다.** 32항목 마스터와 승인 그래프의 통제 목록을 컨텍스트로
   주고, 그 밖은 지어내지 말라고 박아 둔다.

아무것도 쓰지 않는다. 대화는 서버에 남지 않는다 — 남기려면 그것부터 결재
경로를 정해야 하고, 지금은 그 결정이 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..llm import check as check_provider, get_provider
from . import riskassess

#: 사내에서 도는 공급자. 프롬프트가 서버 밖으로 나가지 않는다.
LOCAL_PROVIDERS = ("ollama",)

#: 한 번에 넘길 대화 길이. 길어지면 사내 모델의 컨텍스트를 넘겨 앞이 잘린다 —
#: 잘린 채로 답하면 앞에서 한 말을 잊은 것처럼 보인다.
MAX_TURNS = 8

SYSTEM = """당신은 금융회사의 AI 거버넌스 시스템 안에서 **AI 서비스 기획자를 돕는** 조수다.

지켜야 하는 선이 있다. 이것은 협상 대상이 아니다.

1. **판정하지 않는다.** 위험등급·점수·충족 여부를 말하지 마라. 물으면
   "그건 화면의 룰이 계산합니다 — 여기서는 무엇을 봐야 하는지만 정리해
   드립니다" 라고 답하라.
2. **지어내지 않는다.** 아래 '참고 자료' 에 없는 조문·통제·수치를 만들지 마라.
   모르면 "주어진 자료에는 없습니다" 라고 말하라.
3. **결정을 대신하지 않는다.** "이렇게 하세요" 가 아니라 "이런 것을 확인해야
   합니다" 로 말하라. 서비스 경계와 위험 식별은 사람이 정한다.

하는 일은 이것이다 — 기획 단계에서 놓치기 쉬운 것을 되짚어 주고, 32개 위험
항목 중 무엇이 이 서비스와 닿을지 **후보**를 짚고, 어떤 증적을 미리 준비하면
좋을지 알려 준다.

한국어로, 짧게, 목록으로 답하라. 서론을 붙이지 마라."""


@dataclass
class Reply:
    text: str = ""
    provider: str = ""
    model: str = ""
    local: bool = True
    ok: bool = True
    reason: str = ""
    hint: str = ""
    tried: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text, "provider": self.provider, "model": self.model,
            "local": self.local, "ok": self.ok, "reason": self.reason,
            "hint": self.hint, "tried": self.tried,
        }


def _context(controls: list[dict[str, Any]] | None) -> str:
    """참고 자료 — 32항목과 (있으면) 승인된 통제 목록.

    항목 전문을 다 넣지 않고 계층과 이름만 넣는다. 사내 모델의 컨텍스트가
    한정돼 있어, 다 넣으면 정작 사용자의 질문이 뒤로 밀린다.
    """
    lines = ["[32개 위험 항목 — 번호 · 원칙 · 세부]"]
    for item in riskassess.items():
        lines.append(f"{item['no']}. {item['lv1']} > {item['lv2']} > {item['lv3']}")
    if controls:
        lines.append("")
        lines.append("[승인된 통제 — 코드 · 이름]")
        for c in controls[:40]:
            lines.append(f"{c.get('code')} {c.get('title')}")
    return "\n".join(lines)


def _providers(cfg: Config, allow_external: bool) -> list[str]:
    """사내 먼저, 그다음이 외부. 외부는 허용했을 때만 목록에 들어간다."""
    order = [p for p in cfg.providers if p in LOCAL_PROVIDERS]
    if allow_external:
        order += [p for p in cfg.providers if p not in LOCAL_PROVIDERS and p != "template"]
    return order or list(LOCAL_PROVIDERS)


def chat(
    cfg: Config,
    *,
    messages: list[dict[str, str]],
    service: str = "",
    controls: list[dict[str, Any]] | None = None,
    allow_external: bool = False,
) -> Reply:
    """대화 한 번. 아무것도 쓰지 않는다."""
    turns = [m for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
    if not turns:
        raise ValueError("보낼 말이 없다")
    turns = turns[-MAX_TURNS:]

    head = [f"[참고 자료]\n{_context(controls)}"]
    if service:
        head.append(f"[기획 중인 서비스]\n{service}")
    body = "\n\n".join(head + ["[대화]"] + [
        f"{'기획자' if m['role'] == 'user' else '조수'}: {m['content']}" for m in turns
    ] + ["조수:"])

    out = Reply()
    for name in _providers(cfg, allow_external):
        ready = check_provider(name, cfg.with_provider(name).llm_options)
        if not ready.ok:
            out.tried.append({"provider": name, "error": ready.reason})
            out.reason, out.hint = ready.reason, ready.hint
            continue
        try:
            pcfg = cfg.with_provider(name)
            text = get_provider(name, pcfg.llm_options).complete(SYSTEM, body)
        except Exception as exc:  # noqa: BLE001 — 어떤 공급자든 다음으로 넘긴다
            out.tried.append({"provider": name, "error": str(exc)[:200]})
            continue
        if not str(text).strip():
            out.tried.append({"provider": name, "error": "빈 응답"})
            continue
        out.text = str(text).strip()
        out.provider = name
        out.model = str(pcfg.llm_options.get("model", ""))
        out.local = name in LOCAL_PROVIDERS
        out.ok = True
        return out

    out.ok = False
    if not out.reason:
        out.reason = "사내 sLM 에 닿지 못했다"
    return out

# --------------------------------------------------------------------------- #
# 평가표 질문 초안
#
# 회의: "저희가 처음 만들 때는 이제 100개면 100개 설문을 다 세팅을 해드리고요."
# 그 100개를 손으로 다 치게 두지 않는다. 다만 **초안일 뿐이다** — 관리자가
# 고치고 지우고 발행한다. 모델이 만든 질문이 그대로 기준이 되면, 무엇을 왜
# 묻는지에 대한 근거가 사라진다.
# --------------------------------------------------------------------------- #
DRAFT_SYSTEM = """당신은 금융회사 AI 거버넌스 담당자가 **자가진단 설문 문항**을 만드는 것을 돕는다.

주어진 주제에 대해 담당자(기획·개발·운영)가 답할 수 있는 질문을 만든다.

규칙
1. 한 질문은 한 가지만 묻는다. "그리고" 로 두 개를 붙이지 마라.
2. 담당자가 사실로 답할 수 있어야 한다. 의견이나 평가를 묻지 마라.
   (나쁨: "이 모델은 공정한가?" / 좋음: "학습 데이터의 집단별 분포를 측정했는가?")
3. 응답 유형을 함께 정한다 — yesno(예/아니오) · single(하나 고르기) ·
   multi(여러 개) · scale(척도) · text(서술).
4. single·multi 는 보기를 2개 이상 준다.

아래 형식의 JSON 배열만 출력하라. 설명·서론·코드펜스를 붙이지 마라.

[{"text":"질문", "kind":"yesno", "options":[], "help":"왜 묻는지 한 줄", "item_no":10}]

item_no 는 아래 32항목 중 이 질문이 닿는 번호다. 확실하지 않으면 null 로 두라."""


def draft_questions(
    cfg: Config,
    *,
    topic: str,
    count: int = 6,
    allow_external: bool = False,
) -> tuple[list[dict[str, Any]], Reply]:
    """주제 하나로 질문 초안을 받는다. **전부 초안이다.**

    모델이 형식을 어기면 버린다. 반쯤 파싱된 것을 화면에 올리면 관리자가
    그것을 고치는 데 직접 쓰는 것보다 오래 걸린다.
    """
    subject = topic.strip()
    if not subject:
        raise ValueError("주제가 필요하다")
    n = max(1, min(int(count), 20))

    body = (
        f"[32개 위험 항목]\n{_context(None)}\n\n"
        f"[주제]\n{subject}\n\n"
        f"질문 {n}개를 JSON 배열로."
    )

    out = Reply()
    for name in _providers(cfg, allow_external):
        ready = check_provider(name, cfg.with_provider(name).llm_options)
        if not ready.ok:
            out.tried.append({"provider": name, "error": ready.reason})
            out.reason, out.hint = ready.reason, ready.hint
            continue
        try:
            pcfg = cfg.with_provider(name)
            # 질문 하나가 한국어로 80~120 토큰이다. 대화용 상한을 그대로 쓰면
            # 배열이 중간에서 잘리고, 잘린 JSON 은 통째로 버려진다.
            opts = {**pcfg.llm_options, "num_predict": max(400 * n, 1200)}
            raw = get_provider(name, opts).complete(DRAFT_SYSTEM, body)
        except Exception as exc:  # noqa: BLE001
            out.tried.append({"provider": name, "error": str(exc)[:200]})
            continue

        parsed = _parse_questions(raw)
        if not parsed:
            out.tried.append({"provider": name, "error": "JSON 배열을 얻지 못했다"})
            continue
        out.text = raw.strip()
        out.provider, out.model = name, str(pcfg.llm_options.get("model", ""))
        out.local, out.ok = name in LOCAL_PROVIDERS, True
        return parsed[:n], out

    out.ok = False
    if not out.reason:
        out.reason = "사내 sLM 에 닿지 못했다"
    return [], out


def _salvage(text: str) -> list[dict[str, Any]]:
    """닫히지 않은 JSON 배열에서 **완성된 객체만** 꺼낸다.

    중괄호 깊이를 세면서 자른다. 문자열 안의 중괄호를 세면 안 되므로 따옴표
    상태를 함께 본다 — 한국어 질문에 중괄호가 들어갈 일은 드물지만, 드문 일이
    한 번 나면 목록이 통째로 사라진다.
    """
    import json

    out: list[dict[str, Any]] = []
    depth, start, in_str, esc = 0, -1, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    out.append(json.loads(text[start:i + 1]))
                except json.JSONDecodeError:
                    pass
                start = -1
    return out


def _parse_questions(raw: str) -> list[dict[str, Any]]:
    """모델 출력에서 JSON 배열만 건져 낸다. 코드펜스와 잡담을 견딘다."""
    import json
    import re as _re

    text = _re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=_re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    body = text[start:end + 1]
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # 상한에 걸려 배열이 닫히지 않은 경우 — 완성된 객체만 건져 낸다.
        # 다 버리면 관리자는 아무것도 못 받고, 왜 안 되는지도 모른다.
        data = _salvage(text[start:])
    if not isinstance(data, list):
        return []

    out: list[dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        text_ = str(row.get("text", "")).strip()
        if not text_:
            continue
        kind = str(row.get("kind", "yesno"))
        out.append({
            "text": text_,
            "kind": kind if kind in ("single", "multi", "scale", "yesno", "text") else "yesno",
            "options": [str(o) for o in (row.get("options") or []) if str(o).strip()],
            "help": str(row.get("help", "")).strip(),
            "item_no": row.get("item_no"),
            # 화면이 'sLM 초안' 이라고 표시하기 위한 것. 관리자가 고치면 지운다.
            "drafted_by_slm": True,
        })
    return out
