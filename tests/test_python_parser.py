"""파이썬 파서 회귀 테스트 (FastAPI · Flask · SQLAlchemy · SPARQL).

여기 있는 케이스는 실제 코드에 돌려 보다 한 번씩 깨졌던 것들이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.config import load_config
from llmwiki.indexer import scan
from llmwiki.parsers.pydata import parse_python_data
from llmwiki.parsers.python import parse_python_file

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_py"


@pytest.fixture(scope="module")
def index():
    cfg = load_config(ROOT / "config.yaml").derive(
        name="파이썬 샘플",
        source_roots=[str(SAMPLE)],
        docs_dir=str(ROOT / "docs"),
        index_file=str(ROOT / "docs/index.json"),
    )
    return scan(cfg)


def _by_name(idx, needle):
    return next(p for p in idx.programs if needle in p.name)


# --------------------------------------------------------------------------- #
# 라우트
# --------------------------------------------------------------------------- #
def test_fastapi_router_prefix_is_applied(index):
    """APIRouter(prefix=...) 를 놓치면 산출물이 틀린 주소를 싣는다."""
    prog = _by_name(index, "고객 정보 관리")
    assert "GET /api/v1/customers" in prog.urls
    assert "POST /api/v1/customers" in prog.urls
    assert "DELETE /api/v1/customers/{customer_id}" in prog.urls


def test_flask_blueprint_prefix_and_methods(index):
    prog = _by_name(index, "계좌 리포트")
    assert "GET /report/accounts" in prog.urls
    assert "GET /report/raw" in prog.urls


def test_flask_route_defaults_to_get(tmp_path):
    src = tmp_path / "m.py"
    src.write_text(
        "from flask import Flask\napp = Flask(__name__)\n\n"
        "@app.route('/ping')\ndef ping():\n    return 'ok'\n",
        encoding="utf-8",
    )
    units = parse_python_file(src, tmp_path)
    methods = [m for u in units for m in u.methods if m.name == "ping"]
    assert methods[0].url_mappings == ["GET /ping"]


# --------------------------------------------------------------------------- #
# SQLAlchemy CRUD
# --------------------------------------------------------------------------- #
def test_crud_is_complete_for_shared_table(index):
    """db.add(변수) / 속성변경+commit / chain.delete() 가 모두 잡혀야 CRUD 가 찬다."""
    assert set(index.tables["TB_CUSTOMER"]["crud"]) == {"C", "R", "U", "D"}


def test_insert_of_second_model_is_not_swallowed(index):
    assert "C" in index.tables["TB_CUSTOMER_HIST"]["crud"]


def test_model_defined_in_another_module_is_resolved(index):
    """모델은 models/entities.py, 사용처는 services/ — 파일 단위로만 모으면 전부 놓친다."""
    stmt = index.statements["app.services.customer_service.register.add.Customer"]
    assert stmt.tables == ["TB_CUSTOMER"]
    assert stmt.crud == [["TB_CUSTOMER", "C"]]


def test_attribute_update_needs_a_commit(tmp_path):
    """커밋 없는 속성 대입까지 UPDATE 로 세면 과탐이 된다."""
    models = tmp_path / "m.py"
    models.write_text(
        "class User:\n    __tablename__ = 'users'\n\n"
        "def touch(db, u: User):\n    u.name = 'x'\n",
        encoding="utf-8",
    )
    mapper = parse_python_data(models, tmp_path)
    assert not [s for s in (mapper.statements if mapper else []) if s.kind == "update"]

    models.write_text(
        "class User:\n    __tablename__ = 'users'\n\n"
        "def touch(db, u: User):\n    u.name = 'x'\n    db.commit()\n",
        encoding="utf-8",
    )
    mapper = parse_python_data(models, tmp_path)
    assert [s.tables for s in mapper.statements if s.kind == "update"] == [["USERS"]]


def test_table_names_are_case_normalized(index):
    """원시 SQL 은 대문자, ORM 은 소문자로 나오면 같은 테이블이 둘로 갈라진다."""
    assert "TB_CUSTOMER" in index.tables
    assert "tb_customer" not in index.tables


def test_raw_sql_tables_are_extracted(index):
    prog = _by_name(index, "계좌 리포트")
    assert {"TB_ACCOUNT", "TB_CUSTOMER"} <= set(prog.tables)


def test_no_duplicate_statements_per_scope(index):
    """모듈 스코프와 함수 스코프에서 같은 지점을 두 번 세면 안 된다."""
    ids = [s.full_id for s in index.statements.values()]
    assert len(ids) == len(set(ids))
    assert not [i for i in ids if "<module>" in i]


# --------------------------------------------------------------------------- #
# SPARQL
# --------------------------------------------------------------------------- #
def test_sparql_select_terms(index):
    stmt = index.statements["app.ontology.graph_service.list_classes.sparql"]
    assert stmt.kind == "select"
    assert stmt.tables == ["owl:Class"]


def test_sparql_insert_is_detected(index):
    """INSERT DATA 는 WHERE/SELECT 가 없어 판별 규칙이 느슨하면 통째로 놓친다."""
    stmt = index.statements["app.ontology.graph_service.register_asset.sparql"]
    assert stmt.kind == "insert"
    assert stmt.crud == [["ex:EnergyAsset", "C"]]


def test_sparql_skips_standard_vocabulary(tmp_path):
    src = tmp_path / "q.py"
    src.write_text(
        'from rdflib import Graph\n'
        'g = Graph()\n'
        'def run():\n'
        '    return g.query("""\n'
        '        SELECT ?s WHERE { ?s rdfs:label ?l . ?s dp:code ?c }\n'
        '    """)\n',
        encoding="utf-8",
    )
    mapper = parse_python_data(src, tmp_path)
    terms = mapper.statements[0].tables
    assert not any(t.startswith("rdfs:") for t in terms)


# --------------------------------------------------------------------------- #
# 프로그램 단위
# --------------------------------------------------------------------------- #
def test_routes_are_split_by_business_prefix(tmp_path):
    """main.py 한 파일에 라우트 69개가 몰린 실제 사례 — 통째로 두면 못 읽는다."""
    lines = ["from fastapi import FastAPI", "app = FastAPI()", ""]
    for area in ("auth", "orders", "users"):
        for n in range(6):
            lines += [f'@app.get("/api/v1/{area}/x{n}")', f"def {area}_{n}():", "    return 1", ""]
    (tmp_path / "main.py").write_text("\n".join(lines), encoding="utf-8")

    cfg = load_config(ROOT / "config.yaml").derive(
        name="t", source_roots=[str(tmp_path)],
        docs_dir=str(tmp_path / "d"), index_file=str(tmp_path / "i.json"),
    )
    idx = scan(cfg)
    assert sorted(p.name.split(" · ")[0] for p in idx.programs) == ["auth", "orders", "users"]
    assert all(len(p.urls) == 6 for p in idx.programs)


def test_small_module_is_not_split(index):
    """라우트가 적으면 굳이 쪼개지 않는다."""
    prog = _by_name(index, "고객 정보 관리")
    assert " · " not in prog.name


def test_helper_modules_do_not_become_programs(tmp_path):
    """파이썬은 거의 모든 모듈이 '함수를 가진 서비스'라, 그대로 두면 유틸까지 명세서가 생긴다."""
    (tmp_path / "helpers.py").write_text(
        "def slugify(s):\n    return s.lower()\n", encoding="utf-8"
    )
    cfg = load_config(ROOT / "config.yaml").derive(
        name="t", source_roots=[str(tmp_path)],
        docs_dir=str(tmp_path / "d"), index_file=str(tmp_path / "i.json"),
    )
    assert scan(cfg).programs == []


def test_module_without_docstring_is_named_by_path(tmp_path):
    """app.py 는 디렉터리마다 있다 — 모듈명만 쓰면 다른 프로그램이 같은 이름이 된다."""
    pkg = tmp_path / "cloud"
    pkg.mkdir()
    (pkg / "app.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        '@app.get("/x")\ndef x():\n    return 1\n',
        encoding="utf-8",
    )
    cfg = load_config(ROOT / "config.yaml").derive(
        name="t", source_roots=[str(tmp_path)],
        docs_dir=str(tmp_path / "d"), index_file=str(tmp_path / "i.json"),
    )
    assert scan(cfg).programs[0].name == "cloud/app"


def test_docstring_of_a_function_is_not_used_as_module_title(tmp_path):
    """모듈 docstring 이 없을 때 첫 함수 설명을 가져오면 30개가 같은 이름이 된다."""
    (tmp_path / "svc.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n\n"
        '@app.get("/y")\ndef y():\n    """함수 설명이지 모듈 설명이 아니다."""\n    return 1\n',
        encoding="utf-8",
    )
    cfg = load_config(ROOT / "config.yaml").derive(
        name="t", source_roots=[str(tmp_path)],
        docs_dir=str(tmp_path / "d"), index_file=str(tmp_path / "i.json"),
    )
    assert scan(cfg).programs[0].name != "함수 설명이지 모듈 설명이 아니다."


def test_call_graph_reaches_service_through_module_singleton(index):
    """router 모듈의 `service = CustomerService()` 를 못 따라가면 테이블이 0이 된다."""
    prog = _by_name(index, "고객 정보 관리")
    assert "TB_CUSTOMER" in prog.tables
    assert any("customer_service" in c for c in prog.classes)


def test_impact_across_python_programs(index):
    """두 프로그램이 같은 테이블을 쓰면 영향도가 잡혀야 한다."""
    assert len(index.tables["TB_CUSTOMER"]["programs"]) >= 2


def test_syntax_error_file_is_skipped(tmp_path):
    (tmp_path / "broken.py").write_text("def (: pass", encoding="utf-8")
    (tmp_path / "ok.py").write_text("def fine():\n    return 1\n", encoding="utf-8")
    assert parse_python_file(tmp_path / "broken.py", tmp_path) == []
    assert parse_python_file(tmp_path / "ok.py", tmp_path)
