"""파서 회귀 테스트.

여기 있는 케이스는 전부 실제로 한 번씩 깨졌던 것들이다.
정규식 기반 파서는 이런 지점에서 조용히 틀리므로 반드시 고정해 둔다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.config import load_config
from llmwiki.indexer import scan
from llmwiki.parsers.java import parse_java_file
from llmwiki.parsers.mybatis import parse_mapper_xml
from llmwiki.parsers.scanner import scrub

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample"
JAVA = SAMPLE / "src/main/java/com/gng"


@pytest.fixture(scope="module")
def index():
    return scan(load_config(ROOT / "config.yaml"))


# --------------------------------------------------------------------------- #
# scanner
# --------------------------------------------------------------------------- #
def test_scrub_removes_comments_but_keeps_line_numbers():
    src = 'int a;\n// } 주석 안 중괄호\n/* 여러\n줄 */\nint b;\n'
    out = scrub(src)
    assert out.text.count("\n") == src.count("\n")
    assert "}" not in out.text
    assert "주석" not in out.text


def test_scrub_restores_string_literals_with_quotes():
    """따옴표가 유실되면 @GetMapping("/list.do") 의 URL 을 못 뽑는다."""
    src = 'String s = "hello";'
    out = scrub(src)
    assert '"' not in out.text  # 리터럴은 플레이스홀더로 치환
    assert out.restore(out.text) == src


def test_scrub_ignores_braces_inside_strings():
    out = scrub('String s = "} not a brace {";')
    assert "{" not in out.text and "}" not in out.text


# --------------------------------------------------------------------------- #
# java
# --------------------------------------------------------------------------- #
def test_injected_fields_are_detected_despite_annotation_parens():
    """@Resource(name = "x") 의 괄호를 메서드 괄호로 오인하면 안 된다."""
    (cls,) = parse_java_file(JAVA / "inst/cust/CustomerServiceImpl.java", SAMPLE)
    assert ["CustomerMapper", "customerMapper"] in cls.fields


def test_transactional_methods_are_not_skipped():
    """@Transactional(rollbackFor = Exception.class) 의 `.class` 는 중첩 클래스가 아니다."""
    (cls,) = parse_java_file(JAVA / "inst/cust/CustomerServiceImpl.java", SAMPLE)
    names = {m.name for m in cls.methods}
    assert {"registerCustomer", "modifyCustomer", "removeCustomer"} <= names


def test_url_mappings_are_joined_with_class_level_mapping():
    (cls,) = parse_java_file(JAVA / "inst/cust/CustomerController.java", SAMPLE)
    assert cls.class_mapping == "/inst/cust"
    assert cls.kind == "controller"
    listed = next(m for m in cls.methods if m.name == "list")
    assert listed.url_mappings == ["/list.do"]


def test_class_kinds():
    kinds = {}
    for path in JAVA.rglob("*.java"):
        for cls in parse_java_file(path, SAMPLE):
            kinds[cls.name] = cls.kind
    assert kinds["CustomerController"] == "controller"
    assert kinds["CustomerServiceImpl"] == "serviceimpl"
    assert kinds["CustomerMapper"] == "mapper"
    assert kinds["CustomerVO"] == "vo"


# --------------------------------------------------------------------------- #
# mybatis
# --------------------------------------------------------------------------- #
def test_mapper_include_fragment_is_resolved():
    m = parse_mapper_xml(
        SAMPLE / "src/main/resources/mapper/inst/customer-mapper.xml", SAMPLE
    )
    st = next(s for s in m.statements if s.id == "selectCustomerList")
    assert "CUST_NM" in st.sql  # <include refid="custBaseColumns"/> 가 치환됨


def test_mapper_extracts_tables_and_crud():
    m = parse_mapper_xml(
        SAMPLE / "src/main/resources/mapper/inst/customer-mapper.xml", SAMPLE
    )
    by_id = {s.id: s for s in m.statements}
    assert by_id["selectCustomerList"].tables == ["TB_COM_CODE", "TB_CUST"]
    assert ["TB_CUST", "C"] in by_id["insertCustomer"].crud
    assert ["TB_CUST", "U"] in by_id["updateCustomer"].crud
    assert "searchKeyword" in by_id["selectCustomerList"].params


# --------------------------------------------------------------------------- #
# graph / programs
# --------------------------------------------------------------------------- #
def test_programs_are_one_per_controller(index):
    assert {p.entry_fqn for p in index.programs} == {
        "com.gng.inst.cust.CustomerController",
        "com.gng.channel.acct.AccountController",
    }


def test_program_reaches_sql_through_interface_and_impl(index):
    prog = next(p for p in index.programs if "Customer" in p.entry_fqn)
    ids = {s.split(".")[-1] for s in prog.sql_ids}
    # 컨트롤러 → 서비스 인터페이스 → 구현체 → 매퍼 → SQL 까지 끊기지 않아야 한다
    assert {"selectCustomerList", "insertCustomer", "updateCustomer", "deleteCustomer"} <= ids
    assert "TB_CUST_HIST" in prog.tables  # 트랜잭션 메서드 안쪽까지 추적


def test_layers_are_assigned(index):
    layers = {p.entry_fqn.split(".")[2]: p.layer for p in index.programs}
    assert layers["inst"] == "기관계"
    assert layers["channel"] == "채널계"


def test_impact_analysis_links_programs_sharing_a_table(index):
    from llmwiki.parsers.graph import impact_of

    prog = next(p for p in index.programs if "Customer" in p.entry_fqn)
    result = impact_of(index, prog.id)
    affected = {r["name"] for r in result["affected"]}
    assert "내 계좌 조회" in affected  # TB_CUST / TB_ACCT 공유
