"""언어별 문자열 (ko | en).

산출물(MD·Excel)과 서버 응답 메시지에서 공유한다.
뷰어 UI 문자열은 web/src/i18n.ts 에 따로 둔다.
"""

from __future__ import annotations

from typing import Any

LANGS = ("ko", "en")

DEFAULT_LANG = "ko"


def normalize(lang: str | None, fallback: str = DEFAULT_LANG) -> str:
    if lang in LANGS:
        return lang  # type: ignore[return-value]
    return fallback if fallback in LANGS else DEFAULT_LANG


# --------------------------------------------------------------------------- #
# 서버 응답 메시지
# --------------------------------------------------------------------------- #
MESSAGES: dict[str, dict[str, str]] = {
    "no_index": {
        "ko": "index.json 이 없습니다. `llmwiki parse` 를 먼저 실행하세요.",
        "en": "index.json is missing. Run `llmwiki parse` first.",
    },
    "doc_not_generated": {
        "ko": "'{name}' 의 산출물이 아직 생성되지 않았습니다. `llmwiki generate --only {id}` 를 실행하세요.",
        "en": "The document for '{name}' has not been generated yet. Run `llmwiki generate --only {id}`.",
    },
    "doc_not_found": {
        "ko": "문서를 찾을 수 없습니다.",
        "en": "Document not found.",
    },
    "program_not_found": {
        "ko": "프로그램을 찾을 수 없습니다.",
        "en": "Program not found.",
    },
    "table_not_found": {
        "ko": "테이블을 찾을 수 없습니다.",
        "en": "Table not found.",
    },
    "source_not_found": {
        "ko": "소스 파일을 찾을 수 없습니다.",
        "en": "Source file not found.",
    },
    "source_too_large": {
        "ko": "파일이 너무 큽니다 ({size}바이트). 열람 한도는 {limit}바이트입니다.",
        "en": "File is too large ({size} bytes). The viewer limit is {limit} bytes.",
    },
    "source_binary": {
        "ko": "텍스트로 읽을 수 없는 파일입니다.",
        "en": "This file cannot be read as text.",
    },
    "not_built": {
        "ko": "뷰어가 아직 빌드되지 않았습니다.",
        "en": "The viewer has not been built yet.",
    },
}


def msg(key: str, lang: str, **fmt: Any) -> str:
    entry = MESSAGES.get(key, {})
    text = entry.get(normalize(lang), entry.get(DEFAULT_LANG, key))
    return text.format(**fmt) if fmt else text


# --------------------------------------------------------------------------- #
# 산출물(MD 부록) 라벨
# --------------------------------------------------------------------------- #
DOC_LABELS: dict[str, dict[str, str]] = {
    "ko": {
        "appendix_note": "아래 부록은 소스에서 자동 추출한 것으로, 재생성 시 항상 최신입니다.",
        "appendix_a": "부록 A. 호출 흐름도",
        "appendix_b": "부록 B. CRUD 매트릭스",
        "appendix_c": "부록 C. 영향도 분석",
        "appendix_d": "부록 D. SQL 원문",
        "appendix_e": "부록 E. 분석 대상 소스",
        "crud_header": "| 테이블 | C | R | U | D |",
        "crud_table_col": "테이블",
        "no_tables": "접근하는 테이블이 없습니다.",
        "impact_intro": "이 프로그램이 사용하는 테이블을 함께 쓰는 다른 프로그램입니다.",
        "impact_header": "| 프로그램 | 계층 | 공유 테이블 |",
        "no_impact": "공유 테이블을 쓰는 다른 프로그램이 없습니다.",
        "no_sql": "연결된 SQL 문이 없습니다.",
        "sql_file": "파일",
        "sql_params": "파라미터",
        "none": "(없음)",
        "no_calls": "_호출 관계가 확인되지 않았습니다._",
    },
    "en": {
        "appendix_note": "The appendices below are extracted from the source automatically and are refreshed on every regeneration.",
        "appendix_a": "Appendix A. Call Flow",
        "appendix_b": "Appendix B. CRUD Matrix",
        "appendix_c": "Appendix C. Impact Analysis",
        "appendix_d": "Appendix D. SQL Statements",
        "appendix_e": "Appendix E. Analyzed Sources",
        "crud_header": "| Table | C | R | U | D |",
        "crud_table_col": "Table",
        "no_tables": "No tables are accessed.",
        "impact_intro": "Other programs that share the tables used by this program.",
        "impact_header": "| Program | Layer | Shared tables |",
        "no_impact": "No other program shares these tables.",
        "no_sql": "No SQL statements are linked to this program.",
        "sql_file": "File",
        "sql_params": "Parameters",
        "none": "(none)",
        "no_calls": "_No call relationships were detected._",
    },
}


def label(key: str, lang: str) -> str:
    table = DOC_LABELS.get(normalize(lang), DOC_LABELS[DEFAULT_LANG])
    return table.get(key, DOC_LABELS[DEFAULT_LANG].get(key, key))


# --------------------------------------------------------------------------- #
# Excel 시트/헤더
# --------------------------------------------------------------------------- #
XLSX_LABELS: dict[str, dict[str, Any]] = {
    "ko": {
        "sheet_overview": "개요",
        "sheet_classes": "클래스",
        "sheet_crud": "CRUD",
        "sheet_sql": "SQL",
        "sheet_impact": "영향도",
        "sheet_source": "소스",
        "title_classes": "관련 클래스",
        "title_crud": "CRUD 매트릭스",
        "title_sql": "SQL 목록",
        "title_impact": "영향도 분석",
        "title_source": "분석 대상 소스",
        "head_class_fqn": ["클래스 FQN"],
        "head_crud": ["테이블", "C", "R", "U", "D"],
        "head_sql": ["SQL ID", "유형", "파라미터", "파일", "라인", "SQL"],
        "head_impact": ["프로그램 ID", "업무명", "계층", "공유 테이블"],
        "head_source": ["파일 경로"],
        "overview_rows": [
            "프로그램 ID", "업무명", "계층", "진입 클래스", "호출 URL",
            "서비스 ID", "접근 테이블", "SQL 건수", "생성 일시", "생성 엔진",
        ],
        "body_title": "명세 본문",
        "filename_suffix": "_명세서",
    },
    "en": {
        "sheet_overview": "Overview",
        "sheet_classes": "Classes",
        "sheet_crud": "CRUD",
        "sheet_sql": "SQL",
        "sheet_impact": "Impact",
        "sheet_source": "Sources",
        "title_classes": "Related classes",
        "title_crud": "CRUD matrix",
        "title_sql": "SQL statements",
        "title_impact": "Impact analysis",
        "title_source": "Analyzed sources",
        "head_class_fqn": ["Class FQN"],
        "head_crud": ["Table", "C", "R", "U", "D"],
        "head_sql": ["SQL ID", "Kind", "Parameters", "File", "Line", "SQL"],
        "head_impact": ["Program ID", "Program", "Layer", "Shared tables"],
        "head_source": ["File path"],
        "overview_rows": [
            "Program ID", "Program", "Layer", "Entry class", "URLs",
            "Service IDs", "Tables", "SQL count", "Generated at", "Generator",
        ],
        "body_title": "Specification body",
        "filename_suffix": "_spec",
    },
}


def xlsx(key: str, lang: str) -> Any:
    table = XLSX_LABELS.get(normalize(lang), XLSX_LABELS[DEFAULT_LANG])
    return table.get(key, XLSX_LABELS[DEFAULT_LANG].get(key, key))
