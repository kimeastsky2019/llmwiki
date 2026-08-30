"""파이썬 데이터 접근 추출 — SQLAlchemy · 원시 SQL · SPARQL.

Java 쪽은 Mapper XML 이라는 고정된 자리에 SQL 이 모여 있지만, 파이썬은 코드
곳곳에 흩어져 있다. 그래서 '접근 지점(access site)' 단위로 SqlStatement 를
만든다. 각 지점은 어떤 테이블(또는 온톨로지 용어)을 무슨 연산으로 건드리는지
들고 있으므로, CRUD 매트릭스·영향도·흐름도가 Java 와 똑같이 굴러간다.

MyBatis 와 결정적으로 다른 점 하나: SQLAlchemy 는 `db.add(obj)` 처럼 변수를
거쳐 쓴다. 그래서 함수 스코프 안에서 지역변수 → 모델 타입을 먼저 묶어야
INSERT/UPDATE/DELETE 가 잡힌다. 이 추적이 없으면 CRUD 가 R 만 나온다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ..models import MapperXml, SqlStatement
from .mybatis import _tables as sql_tables

# --------------------------------------------------------------------------- #
# SQLAlchemy
# --------------------------------------------------------------------------- #
# 세션 메서드 → CRUD
SESSION_OPS = {
    "add": "C", "add_all": "C", "bulk_save_objects": "C", "bulk_insert_mappings": "C",
    "merge": "U", "bulk_update_mappings": "U",
    "delete": "D",
    "query": "R", "get": "R", "scalars": "R", "scalar": "R", "refresh": "R",
}
# 쿼리 빌더 함수 → CRUD
BUILDER_OPS = {"select": "R", "insert": "C", "update": "U", "delete": "D"}

KIND_OF = {"C": "insert", "R": "select", "U": "update", "D": "delete"}

# --------------------------------------------------------------------------- #
# SPARQL
# --------------------------------------------------------------------------- #
SPARQL_FORM_RE = re.compile(
    r"\b(SELECT|CONSTRUCT|ASK|DESCRIBE|INSERT\s+DATA|DELETE\s+DATA|INSERT|DELETE|LOAD|CLEAR|DROP)\b",
    re.I,
)
SPARQL_HINT_RE = re.compile(
    r"\b(WHERE|PREFIX|SELECT|CONSTRUCT|ASK|DESCRIBE|INSERT|DELETE|GRAPH|FILTER|OPTIONAL)\b",
    re.I,
)
# `?s a ex:Foo` / `?s rdf:type <http://...>` 의 타입 자리
TYPE_TERM_RE = re.compile(
    r"(?:\ba\b|rdf:type)\s+(?:<([^>\s]+)>|([A-Za-z][\w.-]*:[\w.-]+))", re.I
)
GRAPH_TERM_RE = re.compile(r"\b(?:GRAPH|FROM(?:\s+NAMED)?)\s+<([^>\s]+)>", re.I)
PREFIXED_RE = re.compile(r"\b([A-Za-z][\w.-]*):([A-Za-z][\w.-]*)\b")
SPARQL_VAR_RE = re.compile(r"\?(\w+)")
# 표준 어휘 접두어 — 이걸 '접근 대상'으로 세면 모든 질의가 rdfs:label 을 쓴다
SKIP_PREFIXES = {"http", "https", "urn", "prefix", "rdf", "rdfs", "xsd", "foaf", "dc", "skos"}

SPARQL_FORM_TO_CRUD = {
    "SELECT": "R", "CONSTRUCT": "R", "ASK": "R", "DESCRIBE": "R",
    "INSERT": "C", "INSERT DATA": "C", "LOAD": "C",
    "DELETE": "D", "DELETE DATA": "D", "CLEAR": "D", "DROP": "D",
}

# rdflib / SPARQLWrapper 진입점
SPARQL_CALLS = {"query", "update", "setQuery", "prepareQuery", "parseQuery"}

# 원시 SQL 진입점
RAW_SQL_CALLS = {"execute", "executemany", "text", "exec_driver_sql", "read_sql", "read_sql_query"}


def parse_python_data(
    path: Path, root: Path, models: dict[str, str] | None = None
) -> MapperXml | None:
    """한 파일의 데이터 접근 지점을 MapperXml 한 덩어리로 돌려준다.

    namespace = 모듈 경로. Java 의 Mapper namespace 자리를 그대로 쓴다.

    models 는 **프로젝트 전체**의 클래스명→테이블명 맵이어야 한다. 모델 정의는
    보통 models/entities.py 한 곳에 모여 있고 쓰는 쪽은 다른 모듈이라,
    파일 안에서만 찾으면 CRUD 가 통째로 비어 버린다.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return None

    rel = str(path.relative_to(root)).replace("\\", "/")
    namespace = _module_name(rel)
    models = dict(models or {})
    models.update(_model_tables(tree))

    statements: list[SqlStatement] = []
    seq: dict[str, int] = {}

    def add(st: SqlStatement) -> None:
        n = seq.get(st.id, 0) + 1
        seq[st.id] = n
        if n > 1:
            st.id = f"{st.id}{n}"
        statements.append(st)

    for scope, scope_name in _scopes(tree):
        env = _local_types(scope, models)
        strings = _string_vars(scope)
        for node in _walk_local(scope):
            if not isinstance(node, ast.Call):
                continue
            for st in _orm_statement(node, scope_name, namespace, rel, models, env, source):
                add(st)
            st = _sparql_statement(node, scope_name, namespace, rel, strings, source)
            if st:
                add(st)
            st = _raw_sql_statement(node, scope_name, namespace, rel, strings, source)
            if st:
                add(st)

        # 속성 대입(user.name = x)은 호출이 아니라 UPDATE 규칙을 따로 돌린다.
        # 커밋이 없는 스코프까지 세면 과탐이라, 같은 스코프에 commit/flush 가
        # 있을 때만 인정한다.
        if _commits(scope):
            for cls, line in dict(attribute_updates(scope, models, env)).items():
                table = models[cls]
                add(
                    SqlStatement(
                        id=f"{scope_name}.update.{cls}",
                        namespace=namespace,
                        kind="update",
                        sql=f"# {cls} 인스턴스의 속성을 변경한 뒤 commit — UPDATE {table}",
                        tables=[table],
                        crud=[[table, "U"]],
                        params=[],
                        parameter_type=cls,
                        result_type=None,
                        path=rel,
                        line=line,
                    )
                )

    if not statements and not models:
        return None
    return MapperXml(path=rel, namespace=namespace, statements=statements)


def model_tables(path: Path) -> dict[str, str]:
    """클래스명 → 테이블명. 다른 모듈의 모델도 알아야 하므로 별도로 노출한다."""
    try:
        return _model_tables(ast.parse(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return {}


# --------------------------------------------------------------------------- #
# ORM
# --------------------------------------------------------------------------- #
def _model_tables(tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if (
                isinstance(item, ast.Assign)
                and isinstance(item.targets[0], ast.Name)
                and item.targets[0].id == "__tablename__"
                and isinstance(item.value, ast.Constant)
            ):
                out[node.name] = str(item.value.value).upper()
    return out


def _orm_statement(
    node: ast.Call,
    scope: str,
    namespace: str,
    rel: str,
    models: dict[str, str],
    env: dict[str, str],
    source: str,
) -> list[SqlStatement]:
    verb = node.func.attr if isinstance(node.func, ast.Attribute) else (
        node.func.id if isinstance(node.func, ast.Name) else None
    )
    op = SESSION_OPS.get(verb or "") if isinstance(node.func, ast.Attribute) else None
    if op is None and isinstance(node.func, ast.Name):
        op = BUILDER_OPS.get(verb or "")
    if op is None:
        return []

    found = _models_in(node, models, env)
    if not found and isinstance(node.func, ast.Attribute):
        # session.query(User).filter(...).delete() 처럼 체인 앞쪽에 모델이 있다
        cur: ast.AST | None = node.func.value
        while isinstance(cur, ast.Call):
            found += _models_in(cur, models, env)
            cur = cur.func.value if isinstance(cur.func, ast.Attribute) else None
    if not found:
        return []

    snippet = ast.get_source_segment(source, node) or ""
    out: list[SqlStatement] = []
    for cls in dict.fromkeys(found):
        table = models[cls]
        out.append(
            SqlStatement(
                id=f"{scope}.{verb}.{cls}",
                namespace=namespace,
                kind=KIND_OF[op],
                sql=snippet,
                tables=[table],
                crud=[[table, op]],
                params=sorted(_kwargs_of(node)),
                parameter_type=cls,
                result_type=None,
                path=rel,
                line=node.lineno,
            )
        )
    return out


def _models_in(call: ast.Call, models: dict[str, str], env: dict[str, str]) -> list[str]:
    out: list[str] = []
    for arg in list(call.args) + [k.value for k in call.keywords]:
        cls = _resolve_model(arg, models, env)
        if cls:
            out.append(cls)
    return out


def _resolve_model(node: ast.AST, models: dict[str, str], env: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return node.id if node.id in models else env.get(node.id)
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        return name if name in models else None
    if isinstance(node, ast.Attribute):
        # User.id 처럼 컬럼 참조
        base = node.value
        if isinstance(base, ast.Name):
            return base.id if base.id in models else env.get(base.id)
    return None


def _local_types(scope: ast.AST, models: dict[str, str]) -> dict[str, str]:
    """지역변수 → 모델 클래스. 이게 있어야 db.add(obj) 의 C 가 잡힌다."""
    env: dict[str, str] = {}
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for arg in scope.args.args + scope.args.kwonlyargs:
            if isinstance(arg.annotation, ast.Name) and arg.annotation.id in models:
                env[arg.arg] = arg.annotation.id
    for node in _walk_local(scope):
        if isinstance(node, ast.Assign):
            value = node.value
            cls = None
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                if value.func.id in models:
                    cls = value.func.id
            if cls:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        env[target.id] = cls
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.annotation, ast.Name) and node.annotation.id in models:
                env[node.target.id] = node.annotation.id
    return env


def attribute_updates(
    scope: ast.AST, models: dict[str, str], env: dict[str, str]
) -> list[tuple[str, int]]:
    """`user.name = x` 처럼 속성을 바꾸는 곳 → UPDATE.

    SQLAlchemy 에서 가장 흔한 수정 방식인데 호출이 아니라 대입이라
    호출 기반 규칙만으로는 절대 안 잡힌다.
    """
    out: list[tuple[str, int]] = []
    for node in _walk_local(scope):
        targets: list[ast.AST] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Attribute):
                continue
            base = target.value
            if not isinstance(base, ast.Name):
                continue
            cls = base.id if base.id in models else env.get(base.id)
            if cls:
                out.append((cls, node.lineno))
    return out


def _commits(scope: ast.AST) -> bool:
    for node in _walk_local(scope):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("commit", "flush"):
                return True
    return False


def _kwargs_of(call: ast.Call) -> set[str]:
    out = {k.arg for k in call.keywords if k.arg}
    for arg in call.args:
        if isinstance(arg, ast.Call):
            out |= {k.arg for k in arg.keywords if k.arg}
    return out


# --------------------------------------------------------------------------- #
# SPARQL
# --------------------------------------------------------------------------- #
def _sparql_statement(
    node: ast.Call, scope: str, namespace: str, rel: str, strings: dict[str, str], source: str
) -> SqlStatement | None:
    verb = node.func.attr if isinstance(node.func, ast.Attribute) else (
        node.func.id if isinstance(node.func, ast.Name) else None
    )
    if verb not in SPARQL_CALLS or not node.args:
        return None
    text = _string_of(node.args[0], strings)
    if not text or not _looks_like_sparql(text):
        return None

    form = _sparql_form(text)
    op = SPARQL_FORM_TO_CRUD.get(form, "R")
    terms = _sparql_terms(text)
    return SqlStatement(
        id=f"{scope}.sparql",
        namespace=namespace,
        kind=KIND_OF[op],
        sql=text.strip(),
        tables=terms,
        crud=[[t, op] for t in terms],
        params=sorted(set(SPARQL_VAR_RE.findall(text)))[:20],
        parameter_type=f"SPARQL {form}",
        result_type=None,
        path=rel,
        line=node.lineno,
    )


def _looks_like_sparql(text: str) -> bool:
    if len(SPARQL_HINT_RE.findall(text)) < 2:
        return False
    # SQL 과 헷갈리지 않게: SPARQL 은 변수(?x)나 PREFIX 를 쓴다
    return bool(SPARQL_VAR_RE.search(text) or re.search(r"\bPREFIX\b", text, re.I))


def _sparql_form(text: str) -> str:
    m = SPARQL_FORM_RE.search(text)
    return re.sub(r"\s+", " ", m.group(1).upper()) if m else "SELECT"


def _sparql_terms(text: str) -> list[str]:
    """이 질의가 건드리는 '대상'. 관계형 테이블 자리에 놓는다.

    우선순위: 타입 자리(a / rdf:type) → 명명 그래프 → 그래도 없으면 술어.
    전부 긁어모으면 노이즈라 이 순서로 좁힌다.
    """
    terms: list[str] = []
    for full, prefixed in TYPE_TERM_RE.findall(text):
        terms.append(_short_uri(full) if full else prefixed)
    terms += [_short_uri(u) for u in GRAPH_TERM_RE.findall(text)]
    if not terms:
        # 타입 자리를 못 찾았을 때만 술어에서 유추한다. rdfs:label 같은 표준
        # 어휘와 소문자로 시작하는 술어는 '대상'이 아니라 속성이라 뺀다.
        terms = [
            f"{prefix}:{name}"
            for prefix, name in PREFIXED_RE.findall(text)
            if prefix.lower() not in SKIP_PREFIXES and name[:1].isupper()
        ]
    return sorted({t for t in terms if t})[:20]


def _short_uri(uri: str) -> str:
    tail = re.split(r"[#/]", uri.rstrip("#/"))[-1]
    return tail or uri


# --------------------------------------------------------------------------- #
# 원시 SQL
# --------------------------------------------------------------------------- #
def _raw_sql_statement(
    node: ast.Call, scope: str, namespace: str, rel: str, strings: dict[str, str], source: str
) -> SqlStatement | None:
    verb = node.func.attr if isinstance(node.func, ast.Attribute) else (
        node.func.id if isinstance(node.func, ast.Name) else None
    )
    if verb not in RAW_SQL_CALLS or not node.args:
        return None
    text = _string_of(node.args[0], strings)
    if not text:
        return None
    kind = _sql_kind(text)
    if not kind:
        return None
    tables, crud = sql_tables(text, kind)
    if not tables:
        return None
    return SqlStatement(
        id=f"{scope}.{kind}",
        namespace=namespace,
        kind=kind,
        sql=text.strip(),
        tables=tables,
        crud=crud,
        params=sorted(set(re.findall(r"[:%]\(?(\w+)\)?s?", text)))[:20],
        parameter_type="raw SQL",
        result_type=None,
        path=rel,
        line=node.lineno,
    )


def _sql_kind(text: str) -> str | None:
    head = text.lstrip().split(None, 1)
    if not head:
        return None
    first = head[0].lower()
    if first in ("select", "insert", "update", "delete", "merge", "with"):
        return {"merge": "update", "with": "select"}.get(first, first)
    return None


# --------------------------------------------------------------------------- #
# 공통
# --------------------------------------------------------------------------- #
def _scopes(tree: ast.Module):
    yield tree, "<module>"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, node.name


def _walk_local(scope: ast.AST):
    """스코프 '자기 몫'만 훑는다. 중첩 함수 안으로는 내려가지 않는다.

    ast.walk 로 모듈을 훑으면 함수 본문까지 딸려 와, 같은 접근 지점이
    <module> 과 함수 이름으로 두 번 잡힌다.
    """
    stack: list[ast.AST] = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _string_vars(scope: ast.AST) -> dict[str, str]:
    """query = \"\"\"SELECT ...\"\"\" 처럼 변수에 담긴 질의문."""
    out: dict[str, str] = {}
    for node in _walk_local(scope):
        if not isinstance(node, ast.Assign):
            continue
        text = _literal_text(node.value)
        if text:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = text
    return out


def _string_of(node: ast.AST, strings: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return strings.get(node.id)
    return _literal_text(node)


def _literal_text(node: ast.AST) -> str | None:
    """상수 문자열과 f-string 을 텍스트로. f-string 의 치환부는 자리표시자로 둔다."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            else:
                parts.append("{...}")
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _literal_text(node.left)
        right = _literal_text(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _module_name(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".py") else rel
    parts = [p for p in stem.split("/") if p]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "module"
