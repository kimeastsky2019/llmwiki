"""LLM 없이 동작하는 템플릿 공급자.

용도:
- API 키 없이 파이프라인 전체(파싱 → 산출물 → 뷰어 → Excel)를 검증하는 스모크 테스트
- 망분리 환경 반입 전 데모

정적 분석으로 확인된 사실만 채우고, 서술이 필요한 칸은 비워 둔 채
'LLM 생성 필요' 로 표시한다. 절대 내용을 지어내지 않는다.
"""

from __future__ import annotations

import re
from typing import Any

from ..docgen.prompts import FACT_LABELS

TODO = {"ko": "_(LLM 생성 필요)_", "en": "_(LLM generation required)_"}

STRINGS: dict[str, dict[str, str]] = {
    "ko": {
        "fallback_name": "프로그램",
        "warning": (
            "> ⚠️ 이 문서는 **정적 분석 결과만으로 생성**되었습니다. "
            "서술 항목을 채우려면 LLM 공급자(claude / ollama)로 재생성하세요."
        ),
        "s1": "## 1. 개요",
        "overview_head": "| 항목 | 내용 |",
        "row_name": "화면/업무명",
        "row_entry": "진입 클래스",
        "row_urls": "호출 URL",
        "row_layer": "계층",
        "row_optype": "처리 유형",
        "row_tx": "트랜잭션",
        "none": "(없음)",
        "s2": "## 2. 주요 클래스",
        "class_head": "| 클래스 | 역할 | 설명 |",
        "from_source": "소스상 확인",
        "s3": "## 3. 주요 테이블",
        "table_head": "| 테이블 | 용도 | 접근 방식 |",
        "see_appendix_b": "부록 B 참조",
        "s4": "## 4. 호출 흐름",
        "see_appendix_a": "부록 A 의 자동 생성 흐름도를 참조하십시오.",
        "s5": "## 5. 처리 로직",
        "s6": "## 6. 주요 쿼리",
        "query_head": "| 쿼리 ID | 유형 | 설명 |",
        "s7": "## 7. 입출력 파라미터",
        "s8": "## 8. 오류 코드 / 예외 처리",
        "s9": "## 9. 재사용·개선 포인트",
    },
    "en": {
        "fallback_name": "Program",
        "warning": (
            "> ⚠️ This document was generated **from static analysis only**. "
            "Regenerate with an LLM provider (claude / ollama) to fill in the narrative sections."
        ),
        "s1": "## 1. Overview",
        "overview_head": "| Item | Value |",
        "row_name": "Screen / business name",
        "row_entry": "Entry class",
        "row_urls": "URLs",
        "row_layer": "Layer",
        "row_optype": "Operation type",
        "row_tx": "Transaction",
        "none": "(none)",
        "s2": "## 2. Key Classes",
        "class_head": "| Class | Role | Description |",
        "from_source": "confirmed in source",
        "s3": "## 3. Key Tables",
        "table_head": "| Table | Purpose | Access |",
        "see_appendix_b": "see Appendix B",
        "s4": "## 4. Call Flow",
        "see_appendix_a": "See the automatically generated diagram in Appendix A.",
        "s5": "## 5. Processing Logic",
        "s6": "## 6. Key Queries",
        "query_head": "| Query ID | Kind | Description |",
        "s7": "## 7. Input / Output Parameters",
        "s8": "## 8. Error Codes / Exception Handling",
        "s9": "## 9. Reuse & Improvement Notes",
    },
}

SQL_RE = re.compile(r"^### (\S+)\s+\((\w+)", re.M)


def _fact_re(lang: str) -> re.Pattern[str]:
    L = FACT_LABELS[lang]
    keys = "|".join(
        re.escape(L[k]) for k in ("name", "layer", "entry", "urls", "tables", "crud")
    )
    return re.compile(rf"^- ({keys}): (.*)$", re.M)


def _file_re(lang: str) -> re.Pattern[str]:
    return re.compile(rf"^### {re.escape(FACT_LABELS[lang]['file'])}: (.+)$", re.M)


def _detect_lang(prompt: str) -> str:
    """프롬프트의 사실 블록 머리말로 언어를 판별한다 (system 은 넘어오지만 신뢰하지 않는다)."""
    for lang in ("en", "ko"):
        if FACT_LABELS[lang]["facts_head"] in prompt:
            return lang
    return "ko"


class TemplateProvider:
    name = "template"
    model = "static-only"

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}

    def complete(self, system: str, prompt: str) -> str:  # noqa: ARG002
        lang = _detect_lang(prompt)
        L = STRINGS[lang]
        F = FACT_LABELS[lang]
        todo = TODO[lang]

        facts = dict(_fact_re(lang).findall(prompt))
        files = _file_re(lang).findall(prompt)
        sqls = SQL_RE.findall(prompt)

        name = facts.get(F["name"], L["fallback_name"])
        tables = [t.strip() for t in facts.get(F["tables"], "").split(",") if t.strip()]
        urls = [u.strip() for u in facts.get(F["urls"], "").split(",") if u.strip()]
        # 값이 없을 때 build_prompt 가 넣어둔 "(없음)" 플레이스홀더는 목록으로 세지 않는다
        if urls == [F["none"]]:
            urls = []
        if tables == [F["none"]]:
            tables = []

        out: list[str] = [f"# {name}", ""]
        out += [
            L["warning"],
            "",
            L["s1"],
            "",
            L["overview_head"],
            "|---|---|",
            f"| {L['row_name']} | {name} |",
            f"| {L['row_entry']} | `{facts.get(F['entry'], '')}` |",
            f"| {L['row_urls']} | {', '.join(f'`{u}`' for u in urls) if urls else L['none']} |",
            f"| {L['row_layer']} | {facts.get(F['layer'], '')} |",
            f"| {L['row_optype']} | {todo} |",
            f"| {L['row_tx']} | {todo} |",
            "",
            todo,
            "",
            L["s2"],
            "",
            L["class_head"],
            "|---|---|---|",
        ]
        for f in dict.fromkeys(files):
            out.append(f"| `{f.split('/')[-1]}` | {L['from_source']} | {todo} |")

        out += ["", L["s3"], "", L["table_head"], "|---|---|---|"]
        for t in tables:
            out.append(f"| {t} | {todo} | {L['see_appendix_b']} |")

        out += ["", L["s4"], "", L["see_appendix_a"], ""]
        out += [L["s5"], "", todo, ""]

        out += [L["s6"], "", L["query_head"], "|---|---|---|"]
        for sid, kind in sqls:
            out.append(f"| `{sid.split('.')[-1]}` | {kind} | {todo} |")

        out += [
            "",
            L["s7"],
            "",
            todo,
            "",
            L["s8"],
            "",
            todo,
            "",
            L["s9"],
            "",
            todo,
        ]
        return "\n".join(out)
