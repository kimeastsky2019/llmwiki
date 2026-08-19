"""적재 게이트 — 개인정보보호법 · 인공지능 기본법 검토.

`llmwiki/compliance/` 와 다른 층이다. 저쪽은 **조직의 규정·통제**를 그래프로 두고
서비스가 그 의무를 충족하는지 판정한다. 여기는 **문서 한 건**이 지식베이스에
들어가도 되는지를 적재 직전에 거르는 관문이다.

두 개의 법적 의무가 걸린다.

1. 개인정보보호법 — 문서에 개인정보가 있고 그것을 국외 사업자의 모델로 보내면
   **국외 이전**이다 (제28조의8). LLMWiki 는 공급자를 화면에서 바꿀 수 있으므로
   (사내 Ollama / Anthropic / xAI) 국외 이전 해당성은 **고른 공급자에 따라 달라진다.**
   그래서 목적지를 인자로 받는다 — 하드코딩하면 사내 모델로 돌려도 차단이 뜨거나,
   더 나쁘게는 외부로 보내면서 통과가 뜬다.
2. 인공지능 기본법 — 생성형 AI 로 서술을 만들면 투명성 의무가 붙는다
   (제31조: 사전 고지 + 생성물 표시).

두 검토 모두 **규칙 기반**이다. LLM 에게 "이 문서 개인정보 있나요" 를 묻지 않는다.
탐지 누락이 그대로 법 위반이 되므로 재현 가능하고 감사 가능해야 한다.

판정은 하되 **확정은 사람이 한다.** 이 모듈은 `Finding` 을 만들고 ``resolution`` 은
비워 둔다 (`llmwiki/compliance/rules.py` 의 잠정/확정 분리와 같은 규율).

법령 근거
  - 개인정보보호법 제3조(최소수집), 제23·24조(민감·고유식별), 제29조(안전조치),
    제28조의8(국외 이전), 제28조의9(중지 명령)
  - 인공지능 발전과 신뢰 기반 조성 등에 관한 기본법 (시행 2026.1.22)
    제2조제4호(고영향), 제31조(투명성), 제32조(안전성), 제34조(고영향 사업자 의무),
    제43조(과태료)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

#: 심각도의 닫힌 집합. 순서가 곧 우선순위다.
SEVERITIES: tuple[str, ...] = ("blocker", "error", "warning", "info")

SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}

#: 판정 라벨. 값(코드)은 영어로 저장하고 표시할 때만 번역한다 —
#: `llmwiki/compliance/i18n.py` 와 같은 규율이다.
VERDICTS: tuple[str, ...] = ("BLOCKED", "CONDITIONAL", "ALLOWED")

VERDICT_LABELS: dict[str, dict[str, str]] = {
    "ko": {"BLOCKED": "차단", "CONDITIONAL": "조건부 적재", "ALLOWED": "적재 가능"},
    "en": {"BLOCKED": "Blocked", "CONDITIONAL": "Conditional", "ALLOWED": "Allowed"},
}


@dataclass(frozen=True)
class Destination:
    """문서 내용이 실제로 도달하는 곳.

    `cross_border` 가 국외 이전 해당성을 가른다. 사내 GPU 로만 도는 구성에서는
    같은 문서가 같은 룰을 통과해도 판정이 달라져야 맞다.
    """

    name: str
    cross_border: bool
    note: str = ""


#: 공급자 → 목적지. `llmwiki/compliance/advise.py` 의 LOCAL_PROVIDERS 와 같은 축이다.
DESTINATIONS: dict[str, Destination] = {
    "ollama": Destination("사내 GPU (Ollama)", False, "서버 밖으로 나가지 않는다"),
    "template": Destination("로컬 템플릿", False, "모델 호출이 없다"),
    "claude": Destination("Anthropic (미국)", True),
    "grok": Destination("xAI (미국)", True),
}

#: 모르는 공급자는 **국외로 본다.** 새 공급자가 추가됐을 때 조용히 통과하는 쪽이
#: 아니라 막히는 쪽으로 틀려야 한다.
UNKNOWN_DESTINATION = Destination("알 수 없는 외부 공급자", True, "공급자 미등록 — 보수적으로 국외로 본다")


#: 화면에서 담당자가 고를 수 있는 공급자. 사내 GPU 와 클라우드 API 를 나란히 두어
#: **같은 문서라도 어디로 보내느냐에 따라 판정이 달라진다**는 것이 보이게 한다.
#: 여기에 없는 공급자는 화면에서 고를 수 없다 (`DESTINATIONS` 에는 있어도 마찬가지).
SELECTABLE_PROVIDERS: tuple[str, ...] = ("ollama", "grok")


def destination_for(provider: str | None) -> Destination:
    if not provider:
        return UNKNOWN_DESTINATION
    return DESTINATIONS.get(provider, UNKNOWN_DESTINATION)


def selectable_destinations() -> list[dict[str, Any]]:
    """화면 드롭다운의 유일한 출처. 이름·국외 이전 해당성을 함께 준다 —
    화면이 '사내니까 국내겠지' 하고 따로 판단하면 두 곳이 어긋난다."""
    out: list[dict[str, Any]] = []
    for key in SELECTABLE_PROVIDERS:
        dest = DESTINATIONS[key]
        out.append({
            "provider": key,
            "name": dest.name,
            "cross_border": dest.cross_border,
            "note": dest.note,
        })
    return out


@dataclass
class Finding:
    rule: str
    law: str
    article: str
    severity: str
    title: str
    detail: str
    locations: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    remedy: str = ""
    #: 사람만 채운다. 룰이 채우면 판정과 확정의 구분이 사라진다.
    resolution: str | None = None


# --------------------------------------------------------------------------- #
# 1. 개인정보 탐지
# --------------------------------------------------------------------------- #
def _spaced(word: str) -> str:
    """'담당자' → '담\\s*당\\s*자'.

    한글 업무 문서는 자간을 벌려 조판하는 일이 잦다 ('담 당 자 : 허 만 수').
    이걸 견디지 못하면 탐지 자체가 무의미해진다.
    """
    return r"\s*".join(re.escape(ch) for ch in word)


#: 순서가 의미를 가진다. 구체적인 패턴을 먼저 걸러야 덜 구체적인 패턴이 같은
#: 문자열을 다른 이름으로 덮어쓰지 않는다.
PII_PATTERNS: dict[str, tuple[str, str, str]] = {
    # key: (정규식, 라벨, 심각도)
    "rrn": (r"\b\d{6}-[1-4]\d{6}\b", "주민등록번호", "blocker"),
    "card": (r"\b\d{4}-\d{4}-\d{4}-\d{4}\b", "카드번호", "blocker"),
    "passport": (r"\b[MSRO]\d{8}\b", "여권번호", "blocker"),
    "corp_no": (r"\b\d{6}-\d{7}\b", "법인등록번호", "warning"),
    "biz_no": (r"\b\d{3}-\d{2}-\d{5}\b", "사업자등록번호", "warning"),
    "email": (r"[\w.+-]+@[\w-]+\.[\w.]{2,}", "이메일 주소", "error"),
    "mobile": (r"\b01[016789][-\s]\d{3,4}[-\s]\d{4}\b", "휴대전화번호", "error"),
    # 구분자를 필수로 둔다. 맨 숫자 11자리는 전화번호가 아니라 사용량일 확률이 높다.
    "phone": (r"\(0\d{1,2}\)\s*\d{3,4}[-\s]?\d{4}|\b0\d{1,2}-\d{3,4}-\d{4}\b",
              "전화번호", "error"),
    # 계좌번호는 맥락 없이는 폐기물 분류코드(51-38-01)와 구별되지 않는다.
    # 앞쪽에 금융 어휘가 있을 때만 인정한다 — 준수 도구에서 오탐은 비싸다.
    "account": (r"(?:계좌|예금주|은행|입금)[^\n]{0,20}?\b\d{2,3}-\d{2,6}-\d{2,6}\b",
                "계좌번호", "warning"),
    "address": (r"(?:[가-힣]+(?:특별시|광역시|특별자치시|도|특별자치도))\s*[가-힣]+시\s*"
                r"[가-힣]+(?:면|읍|동)\s*[가-힣0-9\-]+로\s*[\d\-]+",
                "상세주소", "warning"),
}

_ROLES = ("대표자", "대표이사", "담당자", "작성자", "진단수행자", "수행자",
          "검토자", "승인자", "책임자", "연락처", "성명")

#: 직위 뒤에 오는 성명. 직위와 성명 **양쪽 모두** 자간 공백을 허용한다.
NAME_ROLE = re.compile(
    r"(" + "|".join(_spaced(r) for r in _ROLES) + r")"
    r"\s*[:：]?\s*((?:[가-힣]\s*){2,4})(?![가-힣])"
)


def detect_pii(text: str) -> list[dict]:
    """개인정보 탐지. 원문과 공백제거본 양쪽에서 돌린다.

    한 문자열이 여러 패턴에 걸리면 **가장 먼저 선언된(=가장 구체적인) 종류로만** 센다.
    사업자등록번호가 계좌번호로도 잡혀 건수가 부풀면 판정이 왜곡된다.
    """
    hits: list[dict] = []
    claimed: set[str] = set()
    squeezed = re.sub(r"[ \t]+", "", text)

    for key, (pat, label, sev) in PII_PATTERNS.items():
        for src in (text, squeezed):
            for m in re.finditer(pat, src):
                val = m.group(0).strip()
                # 공백 제거본에서 나온 같은 값을 두 번 세지 않는다.
                norm = re.sub(r"\s+", "", val)
                if norm in claimed:
                    continue
                claimed.add(norm)
                hits.append({"kind": key, "label": label, "severity": sev, "value": val})

    seen_names: set[str] = set()
    for src in (text, squeezed):
        for m in NAME_ROLE.finditer(src):
            role = re.sub(r"\s+", "", m.group(1))
            name = re.sub(r"\s+", "", m.group(2))
            if len(name) < 2 or name in seen_names:
                continue
            seen_names.add(name)
            hits.append({
                "kind": "name", "label": f"성명({role})", "severity": "error", "value": name,
            })
    return hits


def mask_text(text: str) -> tuple[str, int]:
    """비식별 처리. 적재 전에 반드시 통과해야 하는 관문.

    값을 지우지 않고 **종류를 남긴 토큰**으로 바꾼다. `[전화번호]` 가 남아 있어야
    "여기에 연락처가 있었다" 는 사실이 검색·감리에서 보존된다.

    성명을 먼저 처리한다. 다른 패턴이 주변 문자열을 먼저 바꿔 버리면 직위-성명의
    인접 관계가 깨져 성명이 살아남는다.
    """
    n = 0

    def _name_sub(m: re.Match) -> str:
        nonlocal n
        n += 1
        role = re.sub(r"\s+", "", m.group(1))
        return role + ": [성명]"

    out = NAME_ROLE.sub(_name_sub, text)

    for _key, (pat, label, _sev) in PII_PATTERNS.items():
        out, k = re.subn(pat, f"[{label}]", out)
        n += k

    return out, n


def verify_masking(text: str) -> dict:
    """마스킹이 실제로 통했는지 되짚는다.

    게이트를 믿지 않고 **검산한다.** 마스킹 규칙에 구멍이 있으면 치환했다고 믿고
    그대로 내보내게 되는데, 그건 마스킹을 안 한 것보다 나쁘다. 잔존이 있으면
    적재를 막는다.
    """
    masked, n = mask_text(text)
    residual = detect_pii(masked)
    return {
        "masked_count": n,
        "residual_count": len(residual),
        "residual": [{"label": r["label"], "value": r["value"]} for r in residual[:10]],
        "clean": not residual,
        "masked_text": masked,
    }


# --------------------------------------------------------------------------- #
# 2. 개인정보보호법 검토
# --------------------------------------------------------------------------- #
def check_privacy(text: str, *, destination: Destination = UNKNOWN_DESTINATION,
                  masking_enabled: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    hits = detect_pii(text)
    if not hits:
        return findings

    by_kind: dict[str, list[dict]] = {}
    for h in hits:
        by_kind.setdefault(h["label"], []).append(h)

    worst = min((SEVERITY_ORDER[h["severity"]] for h in hits), default=3)

    # (1) 국외 이전 — 목적지가 국외일 때만 발생한다
    if destination.cross_border and not masking_enabled:
        findings.append(Finding(
            rule="privacy.cross_border",
            law="개인정보보호법",
            article="제28조의8",
            severity="blocker",
            title=f"개인정보를 포함한 문서를 {destination.name} 로 전송 — 국외 이전에 해당",
            detail=(
                f"문서에서 개인정보 {len(hits)}건({', '.join(by_kind)})이 탐지되었다. "
                f"이를 {destination.name} 의 서버로 보내면 개인정보의 국외 이전에 해당한다. "
                "제28조의8은 ① 정보주체의 별도 동의, ② 법률·조약의 특별 규정, "
                "③ 계약의 체결·이행에 필요한 위탁·보관으로서 처리방침 공개 등 고지 요건 충족, "
                "④ 보호위원회가 인정한 인증, ⑤ 인정 국가·기관 중 하나를 충족할 것을 요구한다. "
                "어느 것도 없이 이전하면 제28조의9에 따른 국외 이전 중지 명령의 대상이 될 수 있다."
            ),
            samples=[f"{h['label']}: {h['value']}" for h in hits[:6]],
            remedy=(
                "적재 전 비식별 게이트를 필수 경로로 둘 것(mask_text). 원문이 필요하면 "
                "사내 공급자(ollama)로 라우팅하고, 국외 이전이 불가피하면 처리방침에 "
                "이전 항목·국가·수탁자·목적·보유기간을 명시하고 별도 동의 절차를 갖출 것."
            ),
        ))
    elif not destination.cross_border:
        findings.append(Finding(
            rule="privacy.domestic_only",
            law="개인정보보호법",
            article="제28조의8",
            severity="info",
            title=f"국외 이전 비해당 — 목적지가 {destination.name}",
            detail=(
                f"개인정보 {len(hits)}건이 탐지되었으나 목적지가 국외가 아니므로 "
                f"제28조의8의 국외 이전 요건은 적용되지 않는다. {destination.note or ''} "
                "다만 최소수집·안전조치 의무는 그대로 남는다."
            ),
            remedy="공급자를 외부 모델로 바꾸면 이 항목이 blocker 로 바뀐다 — 전환 시 재검토.",
        ))

    # (2) 최소수집 — 진단 목적에 개인정보가 필요한가
    findings.append(Finding(
        rule="privacy.minimization",
        law="개인정보보호법",
        article="제3조제1항·제16조",
        severity="warning" if masking_enabled else "error",
        title="업무 목적에 불필요한 개인정보가 문서에 포함됨",
        detail=(
            "에너지 사용량 분석과 투자경제성 판단이라는 처리 목적에 비추어 성명·연락처· "
            f"이메일 등은 필요 최소한을 넘는다. 탐지 항목: {', '.join(by_kind)}. "
            "지식베이스는 원문을 장기 보관하므로 목적 달성 후에도 계속 남는다."
        ),
        samples=[f"{k} {len(v)}건" for k, v in by_kind.items()],
        remedy="적재 시 개인정보 항목을 토큰으로 치환하고, 원본은 별도 접근통제 영역에 보관.",
    ))

    # (3) 고유식별·민감정보 — 마스킹으로 해소되지 않는다
    if worst == SEVERITY_ORDER["blocker"]:
        findings.append(Finding(
            rule="privacy.sensitive",
            law="개인정보보호법",
            article="제23조·제24조",
            severity="blocker",
            title="고유식별정보 또는 민감정보로 분류될 항목 탐지",
            detail="주민등록번호·여권번호·카드번호 등은 원칙적으로 처리가 금지되거나 별도 근거가 필요하다.",
            samples=[f"{h['label']}: {h['value'][:4]}****" for h in hits
                     if h["severity"] == "blocker"][:5],
            remedy="해당 항목은 적재 전 완전 삭제. 마스킹만으로는 불충분.",
        ))

    findings.append(Finding(
        rule="privacy.safeguards",
        law="개인정보보호법",
        article="제29조",
        severity="info",
        title="안전성 확보조치 점검 필요",
        detail=(
            "개인정보가 포함된 문서를 처리하는 시스템은 접근권한 관리, 접근통제, 암호화, "
            "접속기록 보관(1년 이상), 악성프로그램 방지 조치를 갖춰야 한다."
        ),
        remedy="업종 구획 단위 접근권한, 적재·검색 이력 로깅, 저장 시 암호화 여부를 점검할 것.",
    ))

    return findings


# --------------------------------------------------------------------------- #
# 3. 인공지능 기본법 검토
# --------------------------------------------------------------------------- #
#: 제2조제4호가 열거한 고영향 인공지능 영역
HIGH_IMPACT_DOMAINS: tuple[str, ...] = (
    "보건의료", "에너지 공급", "수도 공급", "원자력", "생체인식",
    "채용·평가", "대출 심사", "교통수단 운영", "공공서비스 결정", "수사·기소",
)


def check_ai_act(*, uses_generative_ai: bool = True,
                 output_is_advisory: bool = True,
                 has_output_labeling: bool = False,
                 has_prior_notice: bool = False,
                 has_human_oversight: bool = True) -> list[Finding]:
    """AI기본법 점검.

    고영향 해당 여부는 **판정하지 않는다.** 제2조제4호 열거 영역의 해당성은 정성
    판단이라 룰이 답할 수 있는 질문이 아니다. 판단에 필요한 사실만 모아 사람에게
    넘긴다 — 규제 지식그래프의 L3 유보와 같은 처리다.
    """
    findings: list[Finding] = []
    law = "인공지능 발전과 신뢰 기반 조성 등에 관한 기본법"

    if uses_generative_ai and not has_output_labeling:
        findings.append(Finding(
            rule="ai.transparency.labeling",
            law=law,
            article="제31조제2항",
            severity="error",
            title="생성형 AI 산출물에 표시가 없음",
            detail=(
                "생성형 인공지능으로 만든 결과물에는 그 사실을 표시해야 한다. 본 시스템은 "
                "검색 결과를 근거로 명세·분석 서술을 생성하므로 대상에 해당한다. "
                "생성된 문서·요약·답변 모두에 표시가 필요하다."
            ),
            remedy="산출물 하단에 생성 사실·사용 모델·생성 시각을 고정 표기. 파일 산출물은 "
                   "메타데이터에도 기록.",
        ))

    if uses_generative_ai and not has_prior_notice:
        findings.append(Finding(
            rule="ai.transparency.notice",
            law=law,
            article="제31조제1항",
            severity="error",
            title="생성형 AI 기반 서비스라는 사전 고지가 없음",
            detail=(
                "이용자에게 해당 서비스가 인공지능 기반이라는 사실을 미리 알려야 한다. "
                "위반 시 과태료 부과 대상이다(제43조)."
            ),
            remedy="첫 진입 화면과 결과 화면에 상시 고지 문구 노출.",
        ))

    if not has_human_oversight:
        findings.append(Finding(
            rule="ai.human_oversight",
            law=law,
            article="제34조",
            severity="error",
            title="사람에 의한 감독 장치가 없음",
            detail="고영향 인공지능에 해당할 경우 위험관리·설명방안·이용자보호·인적 감독 및 "
                   "관련 문서 보관(5년) 의무가 부과된다.",
            remedy="결과 확정 단계에 자격자 서명 절차를 두고, 서명 이력을 보관.",
        ))

    findings.append(Finding(
        rule="ai.high_impact.review",
        law=law,
        article="제2조제4호·제34조",
        severity="info",
        title="고영향 인공지능 해당 여부 — 판단 유보 (사람 확인 필요)",
        detail=(
            "법이 열거한 고영향 영역: " + ", ".join(HIGH_IMPACT_DOMAINS) + ". "
            "본 시스템은 에너지 사용 분석과 투자 판단 근거를 제공하지만, 산출물은 "
            f"{'권고·참고' if output_is_advisory else '자동 결정'} 성격이고 최종 판단은 "
            "자격자가 한다. '에너지 공급' 영역 해당성은 정성 판단이므로 룰이 확정하지 않는다."
        ),
        remedy="법무 검토로 해당 여부를 확정하고 결과를 이 항목의 resolution 에 기록할 것. "
               "위험등급 산정은 `llmwiki reg risk` 로 이어진다.",
    ))

    findings.append(Finding(
        rule="ai.safety.threshold",
        law=law,
        article="제32조",
        severity="info",
        title="안전성 확보 의무 — 비해당 추정",
        detail=(
            "제32조의 안전성 확보 의무는 누적 연산량 임계값 등 요건을 모두 충족하는 대규모 "
            "시스템에 적용된다. 본 시스템은 외부 또는 사내 모델을 호출하는 응용 서비스라 "
            "직접 대상은 아닌 것으로 보인다. 다만 모델 제공자의 준수 여부는 별개다."
        ),
        remedy="모델 제공자 변경 시 재검토.",
    ))

    return findings


# --------------------------------------------------------------------------- #
# 4. 통합 리포트
# --------------------------------------------------------------------------- #
def review(text: str, *, destination: Destination = UNKNOWN_DESTINATION,
           masking_enabled: bool = False, lang: str = "ko", **ai_kwargs) -> dict:
    """문서 하나에 대한 통합 검토. LLM 호출이 없다 — 같은 입력이면 같은 답이다."""
    findings = check_privacy(text, destination=destination, masking_enabled=masking_enabled)
    findings += check_ai_act(**ai_kwargs)
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.rule))

    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    blockers = counts.get("blocker", 0)
    verdict = "BLOCKED" if blockers else ("CONDITIONAL" if counts.get("error") else "ALLOWED")
    return {
        "verdict": verdict,
        "verdict_label": VERDICT_LABELS[lang if lang in VERDICT_LABELS else "ko"][verdict],
        "upload_allowed": blockers == 0,
        "counts": counts,
        "pii_detected": len(detect_pii(text)),
        "masking_enabled": masking_enabled,
        "destination": {"name": destination.name, "cross_border": destination.cross_border},
        "findings": [asdict(f) for f in findings],
        "note": (
            "이 검토는 결정론적 규칙의 결과이며 법률 자문이 아니다. "
            "최종 판단과 책임은 담당자에게 있다."
        ),
    }
