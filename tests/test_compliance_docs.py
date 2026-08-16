"""문서 파서 · 구성 검토 · 문서 간 정합성.

실제 회사 산출물(docx)에서 겪은 것들을 여기서 고정한다. 특히 두 가지는
샘플 텍스트로는 절대 드러나지 않았고 실물을 넣고서야 나왔다.

1. 조문 번호가 문서에 글자로 없다 — Word 서식 번호라 복원해야 한다.
2. 조문 번호가 절마다 1부터 다시 시작한다 — 한 문서에 "제1조" 가 열 개 넘게 있다.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from llmwiki.compliance import consistency as cons
from llmwiki.compliance import template as tpl
from llmwiki.compliance.docparse import (
    ParseError,
    ParsedDoc,
    detect_sections,
    parse,
    parse_docx,
    slug,
)

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# --------------------------------------------------------------------------- #
# docx 를 손으로 만들어 넣는다 — 실물 산출물은 저장소에 넣을 수 없다
# --------------------------------------------------------------------------- #
def make_docx(path: Path, body: str, *, numbering: bool = True) -> Path:
    styles = f"""<?xml version="1.0"?>
<w:styles xmlns:w="{W}">
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/><w:pPr><w:numPr><w:numId w:val="7"/></w:numPr></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading3">
    <w:name w:val="heading 3"/>
    <w:pPr><w:numPr><w:numId w:val="7"/><w:ilvl w:val="2"/></w:numPr></w:pPr>
  </w:style>
</w:styles>"""
    numbering_xml = f"""<?xml version="1.0"?>
<w:numbering xmlns:w="{W}">
  <w:abstractNum w:abstractNumId="5">
    <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/>
      <w:lvlText w:val="제%1장"/></w:lvl>
    <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/>
      <w:lvlText w:val="제%2절"/></w:lvl>
    <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="decimalFullWidth"/>
      <w:lvlText w:val="제%3조"/></w:lvl>
  </w:abstractNum>
  <w:num w:numId="7"><w:abstractNumId w:val="5"/></w:num>
</w:numbering>"""
    document = f"""<?xml version="1.0"?>
<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        if numbering:
            z.writestr("word/numbering.xml", numbering_xml)
    return path


def para(text: str, style: str = "") -> str:
    props = f"<w:pPr><w:pStyle w:val='{style}'/></w:pPr>" if style else ""
    return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"


def table(rows: list[list[str]]) -> str:
    body = ""
    for row in rows:
        cells = "".join(f"<w:tc>{para(c)}</w:tc>" for c in row)
        body += f"<w:tr>{cells}</w:tr>"
    return f"<w:tbl>{body}</w:tbl>"


@pytest.fixture
def regulation(tmp_path) -> ParsedDoc:
    """장·절마다 조 번호가 1부터 다시 시작하는 실제 규정 구조."""
    body = (
        para("총 칙", "Heading1")
        + para("(목적) 이 규정은 위험관리를 정한다.", "Heading3")
        + para("(용어 정의) 용어는 다음과 같다.", "Heading3")
        + para("원칙 및 기준", "Heading1")
        + para("(AI윤리기준) 임직원은 윤리기준을 준수하여야 한다.", "Heading3")
    )
    return parse_docx(make_docx(tmp_path / "reg.docx", body), "reg")


# --------------------------------------------------------------------------- #
# ★ 조문 번호 복원
# --------------------------------------------------------------------------- #
def test_article_numbers_are_reconstructed_from_word_numbering(regulation):
    """본문에 '제1조' 라는 글자가 없어도 번호가 복원되어야 한다.

    Word 는 번호를 저장하지 않고 화면에 그린다. 그대로 텍스트만 뽑으면 조문 번호가
    통째로 사라져 조문 앵커를 만들 수 없다 — 실제 규정 문서가 전부 이렇다.
    """
    assert "제1조 (목적)" in regulation.text
    assert "제1장 총 칙" in regulation.text
    numbers = [s.number for s in regulation.sections]
    assert "제1조" in numbers and "제2조" in numbers


def test_article_counter_restarts_inside_each_chapter(regulation):
    """★ 절이 바뀌면 조 번호가 1부터 다시 시작한다 — 번호는 유일하지 않다."""
    articles = [s for s in regulation.sections if s.number.endswith("조")]
    assert [s.number for s in articles] == ["제1조", "제2조", "제1조"]
    assert len({s.number for s in articles}) < len(articles)


def test_number_path_disambiguates_repeated_article_numbers(regulation):
    """번호는 겹쳐도 절 경로는 유일해야 한다. 앵커는 이 경로에서 나온다."""
    articles = [s for s in regulation.sections if s.number.endswith("조")]
    paths = [s.number_path for s in articles]
    assert paths == ["제1장/제1조", "제1장/제2조", "제2장/제1조"]
    assert len(set(paths)) == len(paths)


def test_missing_numbering_is_reported_not_hidden(tmp_path):
    doc = parse_docx(
        make_docx(tmp_path / "plain.docx", para("본문"), numbering=False), "plain")
    assert any("numbering" in w for w in doc.warnings)


# --------------------------------------------------------------------------- #
# 오프셋 — 근거 스팬의 기준 좌표
# --------------------------------------------------------------------------- #
def test_section_offsets_point_at_the_real_text(regulation):
    for s in regulation.sections:
        assert regulation.text[s.start:s.end].startswith(s.number or s.title[:4])


def test_parsing_is_stable_across_runs(tmp_path):
    path = make_docx(tmp_path / "a.docx", para("(목적) 정한다.", "Heading3"))
    first, second = parse_docx(path, "a"), parse_docx(path, "a")
    assert first.text == second.text
    assert first.sha256 == second.sha256


def test_tables_become_text_so_they_can_be_cited(tmp_path):
    """업무 문서의 내용은 대부분 표 안에 있다. 버리면 근거로 쓸 문장이 없다."""
    body = para("1. 개요") + table([["구분", "내용"], ["모델", "XGBoost"]])
    doc = parse_docx(make_docx(tmp_path / "t.docx", body), "t")
    assert "| 구분 | 내용 |" in doc.text
    assert "| 모델 | XGBoost |" in doc.text


def test_unsupported_format_is_refused(tmp_path):
    bad = tmp_path / "x.hwp"
    bad.write_bytes(b"\x00")
    with pytest.raises(ParseError):
        parse(bad)


def test_slug_keeps_korean():
    assert slug("별첨01. AI 서비스 기획서") == "별첨01-ai-서비스-기획서"


# --------------------------------------------------------------------------- #
# 서식이 없는 문서 — 본문 머리표로 절을 찾는다
# --------------------------------------------------------------------------- #
FORM = """별첨1. AI 서비스 기획서
I. AI 서비스 개요
1. AI 서비스 개요
| 구분 | 내용 |
| 서비스명 | …… |
2. 서비스 유형 및 채널 구분
II. AI 업무요건
가. AI 모델
"""


def test_style_less_form_is_split_by_its_numbering():
    doc = ParsedDoc("form", "form", "docx", FORM)
    doc.sections = detect_sections(FORM)
    labels = [s.label for s in doc.sections]
    assert "I. AI 서비스 개요" in labels
    assert "II. AI 업무요건" in labels
    assert any(s.number == "가." for s in doc.sections)


def test_required_sections_skip_the_deep_details():
    doc = ParsedDoc("form", "form", "docx", FORM)
    doc.sections = detect_sections(FORM)
    required = [r.label for r in tpl.required_sections(doc, max_level=2)]
    assert "I. AI 서비스 개요" in required
    assert not any(r.startswith("가.") for r in required)   # 세부까지 강제하지 않는다


# --------------------------------------------------------------------------- #
# 구성 검토
# --------------------------------------------------------------------------- #
def _doc(text: str) -> ParsedDoc:
    d = ParsedDoc("w", "w", "docx", text)
    d.sections = detect_sections(text)
    return d


def test_review_finds_the_missing_section():
    work = _doc("I. AI 서비스 개요\n내용을 채웠다.\n")
    report = tpl.review(work, ["I. AI 서비스 개요", "II. AI 업무요건"])
    assert report.present == ["I. AI 서비스 개요"]
    assert report.missing == ["II. AI 업무요건"]
    assert not report.ok


def test_review_tolerates_a_reworded_heading():
    """작업자는 서식 제목을 조금씩 고쳐 쓴다. 완전 일치를 요구하면 다 미충족이 된다."""
    work = _doc("1. 서비스 개요\n채운 내용이 충분히 들어 있다.\n")
    report = tpl.review(work, ["1. AI 서비스 개요"])
    assert report.missing == []


def test_review_flags_a_heading_with_nothing_under_it():
    work = _doc("I. AI 서비스 개요\nII. AI 업무요건\n적어 둔 내용이 여기 있다.\n")
    report = tpl.review(work, ["I. AI 서비스 개요", "II. AI 업무요건"])
    assert "I. AI 서비스 개요" in report.empty_sections


def test_placeholders_left_in_the_form_are_found():
    work = _doc("1. 개요\n| 서비스명 | …… |\n| 승인일 | YYYY. MM. DD |\n")
    holes = tpl.find_placeholders(work)
    whys = {h["why"] for h in holes}
    assert "말줄임표만 남음" in whys
    assert "날짜 서식 미기입" in whys
    assert all(work.text[h["start"]:h["end"]] == h["quote"] or h["quote"] in work.text
               for h in holes)


def test_a_filled_document_has_no_placeholders():
    work = _doc("1. 개요\n| 서비스명 | 여신심사 스코어링 |\n| 승인일 | 2026-03-11 |\n")
    assert tpl.find_placeholders(work) == []


# --------------------------------------------------------------------------- #
# 문서 간 정합성
# --------------------------------------------------------------------------- #
PLAN = "1. 성능 요건\n| 모델 AUC 임계치 | 0.75 |\n| 재학습 주기 | 6 개월 |\n| 고영향 해당 | 예 |\n"
VERIFY = "1. 검증 결과\n| 모델 AUC 임계치 | 0.70 |\n| 재학습 주기 | 6개월 |\n| 고영향 해당 | 아니오 |\n"


def test_conflicting_values_across_documents_are_found():
    conflicts = cons.compare([_doc2("기획서", PLAN), _doc2("검증결과서", VERIFY)])
    keys = {c.key for c in conflicts}
    assert "모델auc임계치" in keys
    assert "고영향해당" in keys


def test_same_value_written_differently_is_not_a_conflict():
    """'6 개월' 과 '6개월' 은 같은 값이다. 여기서 거짓 경보가 나면 아무도 안 본다."""
    conflicts = cons.compare([_doc2("a", PLAN), _doc2("b", VERIFY)])
    assert not any(c.key.startswith("재학습") for c in conflicts)


def test_free_text_is_not_compared():
    """자유 서술은 표현이 달라도 같은 뜻일 수 있다 — 대조 대상이 아니다."""
    a = _doc2("a", "| 목적 | 여신 심사를 자동화한다 |\n")
    b = _doc2("b", "| 목적 | 여신 심사 자동화 |\n")
    assert cons.compare([a, b]) == []


def test_one_document_alone_never_conflicts():
    assert cons.compare([_doc2("a", PLAN)]) == []


def test_conflict_claims_carry_offsets_into_the_source():
    a, b = _doc2("기획서", PLAN), _doc2("검증결과서", VERIFY)
    conflict = next(c for c in cons.compare([a, b]) if c.key == "모델auc임계치")
    texts = {"기획서": PLAN, "검증결과서": VERIFY}
    for group in conflict.values.values():
        for claim in group:
            assert texts[claim.doc_id][claim.start:claim.end] == claim.raw


@pytest.mark.parametrize(
    "raw,expected",
    [("0.750", "0.75"), ("1,200", "1200"), ("80 %", "80%"), ("예", "Y"),
     ("아니오", "N"), ("2026. 2. 25.", "2026-02-25"), ("여신심사 자동화", None)],
)
def test_value_normalization(raw, expected):
    assert cons.normalize_value(raw) == expected


def _doc2(doc_id: str, text: str) -> ParsedDoc:
    d = ParsedDoc(doc_id, doc_id, "txt", text)
    d.sections = detect_sections(text)
    return d
