"""파이썬 소스 파서 (FastAPI / Flask / SQLAlchemy / rdflib).

Java 파서와 달리 정규식이 아니라 표준 라이브러리 `ast` 를 쓴다. 문법을 정확히
읽으므로 "특이한 코드는 놓칠 수 있다"는 제약이 없다. 대신 파이썬은 동적 타입이라
호출 대상 해석은 타입힌트·지역변수 대입·import 로 추론한다.

산출물 모델(JavaClass/JavaMethod/SqlStatement)은 Java 쪽과 공유한다.
이름은 Java 에서 왔지만 담는 내용은 언어 중립이라, 뷰어·문서생성·Excel 이
그대로 재사용된다.

  파이썬 개념      → 공유 모델
  ---------------------------------------------------
  모듈             → JavaClass(kind="module")  (모듈 최상위 함수를 담는 그릇)
  클래스           → JavaClass
  데코레이터       → annotations
  APIRouter prefix → class_mapping
  라우트           → JavaMethod.url_mappings  ["GET /api/x"]
  DB/SPARQL 접근   → JavaMethod.sql_refs → SqlStatement
"""

from __future__ import annotations

import ast
from pathlib import Path

from ..models import JavaClass, JavaMethod

# 라우트 데코레이터를 붙이는 객체 이름. FastAPI/Flask 관습을 따른다.
ROUTER_OBJECTS = {"app", "router", "api", "bp", "blueprint", "apirouter"}
HTTP_VERBS = {"get", "post", "put", "delete", "patch", "head", "options"}

# 클래스 종류 판정에 쓰는 기반 클래스·데코레이터
MODEL_BASES = {"Base", "DeclarativeBase", "Model", "SQLModel"}
SCHEMA_BASES = {"BaseModel", "BaseSettings", "TypedDict", "Enum", "IntEnum", "StrEnum"}


def parse_python_file(path: Path, root: Path) -> list[JavaClass]:
    """한 파일에서 모듈 그릇 + 클래스들을 뽑는다."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        try:
            source = path.read_text(encoding="euc-kr", errors="replace")
        except OSError:
            return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # 문법이 깨진 파일은 조용히 건너뛴다 (파이썬 2 잔재, 템플릿 등)
        return []

    rel = str(path.relative_to(root)).replace("\\", "/")
    module = _module_name(rel)
    imports = _imports(tree)
    routers = _router_prefixes(tree)

    out: list[JavaClass] = []
    module_methods: list[JavaMethod] = []

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out.append(_class_of(node, rel, module, imports, routers, source))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            module_methods.append(_method_of(node, routers, source))

    # 모듈 최상위 함수는 모듈 이름의 그릇에 담는다. FastAPI/Flask 는 라우트를
    # 클래스 없이 모듈에 늘어놓는 경우가 대부분이라 이 그릇이 사실상 주역이다.
    if module_methods or not out:
        out.append(
            JavaClass(
                path=rel,
                package=module.rsplit(".", 1)[0] if "." in module else "",
                name=module.rsplit(".", 1)[-1],
                kind=_module_kind(module_methods),
                annotations=[],
                imports=imports,
                fields=_module_assigns(tree),
                methods=module_methods,
                class_mapping=_common_prefix(routers),
                source=source,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# 클래스 / 함수
# --------------------------------------------------------------------------- #
def _class_of(
    node: ast.ClassDef,
    rel: str,
    module: str,
    imports: list[str],
    routers: dict[str, str],
    source: str,
) -> JavaClass:
    bases = [_name_of(b) for b in node.bases if _name_of(b)]
    decorators = [_decorator_text(d) for d in node.decorator_list]

    fields: list[list[str]] = []
    tablename = ""
    methods: list[JavaMethod] = []

    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_method_of(item, routers, source))
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            fields.append([_annotation_text(item.annotation), item.target.id])
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "__tablename__" and isinstance(item.value, ast.Constant):
                    tablename = str(item.value.value)
                fields.append([_value_type(item.value), target.id])

    return JavaClass(
        path=rel,
        package=module,
        name=node.name,
        kind=_class_kind(node.name, bases, decorators, methods, tablename),
        is_interface=any(b in ("ABC", "Protocol") for b in bases),
        annotations=decorators,
        extends=bases[0] if bases else None,
        implements=bases[1:],
        imports=imports,
        # __tablename__ 은 필드 목록의 맨 앞에 둔다 (ORM 파서가 여기서 읽는다)
        fields=([["__tablename__", tablename]] if tablename else []) + fields,
        methods=methods,
        class_mapping="",
        source=source,
    )


def _method_of(
    node: ast.FunctionDef | ast.AsyncFunctionDef, routers: dict[str, str], source: str
) -> JavaMethod:
    decorators = [_decorator_text(d) for d in node.decorator_list]
    params = [
        [_annotation_text(a.annotation) if a.annotation else "", a.arg]
        for a in node.args.args + node.args.kwonlyargs
        if a.arg not in ("self", "cls")
    ]
    return JavaMethod(
        name=node.name,
        return_type=_annotation_text(node.returns) if node.returns else "",
        params=params,
        annotations=decorators,
        url_mappings=_routes_of(node, routers),
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
        calls=_calls_of(node),
        sql_refs=[],
        body=ast.get_source_segment(source, node) or "",
    )


def _routes_of(
    node: ast.FunctionDef | ast.AsyncFunctionDef, routers: dict[str, str]
) -> list[str]:
    """@router.get("/x") / @app.route("/x", methods=["POST"]) → ["GET /prefix/x"]."""
    out: list[str] = []
    for dec in node.decorator_list:
        if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
            continue
        obj = _name_of(dec.func.value)
        if not obj or obj.split(".")[-1].lower() not in ROUTER_OBJECTS:
            continue
        verb = dec.func.attr.lower()
        path = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else ""
        if not isinstance(path, str):
            continue
        prefix = routers.get(obj, "")
        full = _join(prefix, path)

        if verb in HTTP_VERBS:
            out.append(f"{verb.upper()} {full}")
        elif verb == "route":
            # Flask: methods= 를 안 주면 GET 이 기본
            methods = _flask_methods(dec) or ["GET"]
            out.extend(f"{m} {full}" for m in methods)
    return out


def _flask_methods(dec: ast.Call) -> list[str]:
    for kw in dec.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
            return [
                e.value.upper()
                for e in kw.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
    return []


def _calls_of(node: ast.AST) -> list[list[str]]:
    """`svc.do()` → ["svc", "do"], `helper()` → ["", "helper"]."""
    out: list[list[str]] = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        if isinstance(sub.func, ast.Attribute):
            recv = _name_of(sub.func.value)
            if recv:
                out.append([recv, sub.func.attr])
        elif isinstance(sub.func, ast.Name):
            out.append(["", sub.func.id])
    return out


# --------------------------------------------------------------------------- #
# 모듈 수준 정보
# --------------------------------------------------------------------------- #
def _router_prefixes(tree: ast.Module) -> dict[str, str]:
    """router = APIRouter(prefix="/ontology") → {"router": "/ontology"}.

    prefix 를 놓치면 URL 이 절반만 남아 산출물이 틀린 주소를 싣게 된다.
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = _name_of(node.value.func) or ""
        if func.split(".")[-1] not in ("APIRouter", "Blueprint", "FastAPI", "Flask"):
            continue
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg in ("prefix", "url_prefix") and isinstance(kw.value, ast.Constant):
                prefix = str(kw.value.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                out[target.id] = prefix
    return out


def _imports(tree: ast.Module) -> list[str]:
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.extend(f"{node.module}.{a.name}" for a in node.names)
    return sorted(set(out))


def _module_assigns(tree: ast.Module) -> list[list[str]]:
    """모듈 최상위 대입 — 싱글턴 서비스 인스턴스 추적에 쓴다."""
    out: list[list[str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out.append([_value_type(node.value), target.id])
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.append([_annotation_text(node.annotation), node.target.id])
    return out


# --------------------------------------------------------------------------- #
# 종류 판정
# --------------------------------------------------------------------------- #
def _class_kind(
    name: str,
    bases: list[str],
    decorators: list[str],
    methods: list[JavaMethod],
    tablename: str,
) -> str:
    if tablename or any(b.split(".")[-1] in MODEL_BASES for b in bases):
        return "mapper"  # 테이블을 들고 있는 것 = Java 의 Mapper 자리
    if any(m.url_mappings for m in methods):
        return "controller"
    if any(b.split(".")[-1] in SCHEMA_BASES for b in bases):
        return "vo"
    lowered = name.lower()
    if lowered.endswith(("repository", "dao", "store")):
        return "dao"
    if lowered.endswith(("service", "manager", "usecase", "handler", "engine", "loader")):
        return "service"
    if lowered.endswith(("config", "settings", "schema", "dto", "vo", "request", "response")):
        return "vo"
    return "service" if methods else "util"


def _module_kind(methods: list[JavaMethod]) -> str:
    if any(m.url_mappings for m in methods):
        return "controller"
    return "service" if methods else "util"


# --------------------------------------------------------------------------- #
# 헬퍼
# --------------------------------------------------------------------------- #
def _module_name(rel: str) -> str:
    stem = rel[:-3] if rel.endswith(".py") else rel
    parts = [p for p in stem.split("/") if p]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or "module"


def _name_of(node: ast.AST | None) -> str:
    """Name / Attribute 를 점 표기 문자열로. 그 외는 빈 문자열."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name_of(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _annotation_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - 표현식이 특이해도 파싱 자체는 이어간다
        return _name_of(node)


def _decorator_text(node: ast.AST) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    return f"@{_name_of(target) or _annotation_text(target)}"


def _value_type(node: ast.AST) -> str:
    """대입 우변에서 타입을 짐작한다. `Foo()` → "Foo"."""
    if isinstance(node, ast.Call):
        return _name_of(node.func).split(".")[-1]
    if isinstance(node, ast.Constant):
        return type(node.value).__name__
    return ""


def _join(prefix: str, path: str) -> str:
    if not prefix:
        return path or "/"
    if not path or path == "/":
        return prefix
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def _common_prefix(routers: dict[str, str]) -> str:
    prefixes = {p for p in routers.values() if p}
    return prefixes.pop() if len(prefixes) == 1 else ""
