"""호출 그래프 / 프로그램 단위 / 영향도 인덱스 구성."""

from __future__ import annotations

import fnmatch
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..models import JavaClass, MapperXml, Program, SqlStatement

JAVADOC_RE = re.compile(r"/\*\*(.*?)\*/\s*(?:@\w+[^\n]*\s*)*\s*(?:public\s+|abstract\s+|final\s+)*(?:class|interface)\s+(\w+)", re.S)
LOCAL_VAR_RE = re.compile(r"\b([A-Z][\w]*(?:<[^;=\n]*>)?)\s+(\w+)\s*=")
# 파이썬은 `svc = CustomerService()` — 타입이 우변에 온다
PY_LOCAL_VAR_RE = re.compile(r"^\s*(\w+)\s*=\s*([A-Z]\w*)\s*\(", re.M)
# 파이썬 docstring 블록. 업무명은 여기서 첫 비어 있지 않은 줄을 쓴다.
PY_DOC_BLOCK_RE = re.compile(r'("""|\'\'\')(.*?)\1', re.S)
# 모듈 docstring 인지 판별할 때 '이미 코드가 시작됐는가' 를 보는 표식
PY_CODE_START_RE = re.compile(r'^\s*(?:def |class |@|import |from )', re.M)

# URL 에서 업무 단위를 못 나타내는 껍데기 세그먼트
GENERIC_SEGMENTS = {"api", "rest", "service", "services", "v1", "v2", "v3", "public", "internal"}
# 모듈 하나에 라우트가 이보다 많으면 업무 프리픽스로 쪼갠다.
# main.py 한 파일에 라우트 69개가 몰린 실제 사례가 있어 필요하다.
MAX_ROUTES_PER_PROGRAM = 12

FRAMEWORK_PREFIXES = (
    "java.", "javax.", "org.springframework", "org.apache", "lombok",
    "com.fasterxml", "org.slf4j", "org.junit",
)


@dataclass
class Index:
    project: str
    classes: dict[str, JavaClass] = field(default_factory=dict)
    mappers: dict[str, MapperXml] = field(default_factory=dict)
    statements: dict[str, SqlStatement] = field(default_factory=dict)
    programs: list[Program] = field(default_factory=list)
    edges: list[list[str]] = field(default_factory=list)  # [from, to, kind]
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)


def build_index(
    project: str,
    classes: list[JavaClass],
    mappers: list[MapperXml],
    layers: list[dict[str, str]],
) -> Index:
    idx = Index(project=project)
    for c in classes:
        idx.classes[c.fqn] = c
    for m in mappers:
        idx.mappers[m.namespace] = m
        for st in m.statements:
            idx.statements[st.full_id] = st

    # 파이썬은 SQL/SPARQL 접근 지점이 함수 안에 흩어져 있다. Mapper 인터페이스처럼
    # 이름 규칙으로 이어지지 않으므로 파일+스코프로 메서드에 되붙인다.
    _link_python_statements(idx)

    simple = _simple_name_map(idx.classes)
    edges: set[tuple[str, str, str]] = set()

    for fqn, cls in idx.classes.items():
        var_types = _var_types(cls, simple)
        for method in cls.methods:
            src = f"{fqn}#{method.name}"
            local = dict(var_types)
            local.update(_local_var_types(method, simple, _is_python(cls)))
            for recv, called in method.calls:
                target_fqn = local.get(recv)
                if not target_fqn:
                    continue
                edges.add((src, f"{target_fqn}#{called}", "call"))

            # Mapper 인터페이스는 메서드명이 곧 SQL id
            if cls.kind in ("mapper",) and not method.body:
                sid = f"{fqn}.{method.name}"
                if sid in idx.statements:
                    edges.add((src, sid, "sql"))

            # DAO 가 sqlSession.selectList("ns.id") 형태로 직접 호출
            for ref in method.sql_refs:
                if ref in idx.statements:
                    edges.add((src, ref, "sql"))
                else:
                    match = _resolve_sql_ref(ref, idx.statements)
                    if match:
                        edges.add((src, match, "sql"))

    # Mapper 인터페이스 메서드 → SQL (호출자 없이도 연결)
    for fqn, cls in idx.classes.items():
        if cls.kind != "mapper":
            continue
        for method in cls.methods:
            sid = f"{fqn}.{method.name}"
            if sid in idx.statements:
                edges.add((f"{fqn}#{method.name}", sid, "sql"))

    # 인터페이스 → 구현체 (호출 흐름이 끊기지 않도록 명시적으로 잇는다)
    for fqn, cls in idx.classes.items():
        if not cls.is_interface or cls.kind == "mapper":
            continue
        for impl_fqn in _implementations_of(cls, idx.classes):
            impl = idx.classes[impl_fqn]
            impl_methods = {m.name for m in impl.methods}
            for method in cls.methods:
                if method.name in impl_methods:
                    edges.add((f"{fqn}#{method.name}", f"{impl_fqn}#{method.name}", "impl"))

    idx.edges = sorted([list(e) for e in edges])
    idx.programs = _build_programs(idx, layers)
    idx.tables = _build_tables(idx)
    return idx


# --------------------------------------------------------------------------- #
# 타입 해석
# --------------------------------------------------------------------------- #
def _simple_name_map(classes: dict[str, JavaClass]) -> dict[str, str]:
    out: dict[str, str] = {}
    for fqn, cls in classes.items():
        out.setdefault(cls.name, fqn)
    return out


def _base_type(t: str) -> str:
    t = t.split("<")[0].replace("[]", "").strip()
    return t.split(".")[-1]


def _var_types(cls: JavaClass, simple: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ftype, fname in cls.fields:
        target = simple.get(_base_type(ftype))
        if target:
            out[fname] = target
    return out


def _local_var_types(method, simple: dict[str, str], python: bool = False) -> dict[str, str]:
    out: dict[str, str] = {}
    for ptype, pname in method.params:
        target = simple.get(_base_type(ptype))
        if target and pname:
            out[pname] = target
    if python:
        for mname, mtype in PY_LOCAL_VAR_RE.findall(method.body or ""):
            target = simple.get(_base_type(mtype))
            if target:
                out[mname] = target
    else:
        for mtype, mname in LOCAL_VAR_RE.findall(method.body or ""):
            target = simple.get(_base_type(mtype))
            if target:
                out[mname] = target
    return out


def _is_python(cls: JavaClass) -> bool:
    return cls.path.endswith(".py")


def _link_python_statements(idx: Index) -> None:
    """파이썬 접근 지점(`함수명.verb.Model`)을 해당 메서드의 sql_refs 에 붙인다."""
    by_path: dict[str, list[SqlStatement]] = defaultdict(list)
    for st in idx.statements.values():
        if st.path.endswith(".py"):
            by_path[st.path].append(st)
    if not by_path:
        return
    for cls in idx.classes.values():
        if not _is_python(cls):
            continue
        for method in cls.methods:
            refs = [
                st.full_id
                for st in by_path.get(cls.path, [])
                if st.id.split(".")[0] == method.name
            ]
            if refs:
                method.sql_refs = sorted(set(method.sql_refs) | set(refs))


def _resolve_sql_ref(ref: str, statements: dict[str, SqlStatement]) -> str | None:
    """'custDAO.selectCust' 처럼 짧은 참조를 실제 statement 로 매칭."""
    tail = ref.split(".")[-1]
    hits = [k for k in statements if k.endswith("." + tail)]
    return hits[0] if len(hits) == 1 else None


# --------------------------------------------------------------------------- #
# 프로그램 단위
# --------------------------------------------------------------------------- #
def _build_programs(idx: Index, layers: list[dict[str, str]]) -> list[Program]:
    out_edges: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for src, dst, kind in idx.edges:
        out_edges[src].append((dst, kind))

    programs: list[Program] = []
    covered: set[str] = set()

    entries = [c for c in idx.classes.values() if c.kind == "controller"]
    for cls in entries:
        # 파이썬은 라우트가 모듈 하나에 수십 개씩 몰리기도 한다. 그대로 두면
        # 명세서 한 장에 69개 API 가 들어가 아무도 못 읽는다 — 업무 단위로 쪼갠다.
        for group in _route_groups(cls):
            programs.append(
                _program_from(
                    cls, idx, out_edges, layers, covered,
                    methods=group.methods, suffix=group.key, title=group.title,
                )
            )

    # 컨트롤러에 잡히지 않은 서비스(배치/내부 모듈)도 프로그램으로.
    # 다만 파이썬은 거의 모든 모듈이 '함수를 가진 서비스'라, 그대로 두면
    # 유틸까지 명세서가 생긴다 — 데이터를 실제로 만지는 것만 남긴다.
    for cls in idx.classes.values():
        if cls.kind not in ("service", "serviceimpl"):
            continue
        if cls.fqn in covered:
            continue
        if _is_python(cls) and not any(m.sql_refs for m in cls.methods):
            continue
        programs.append(_program_from(cls, idx, out_edges, layers, covered))

    programs.sort(key=lambda p: (p.layer, p.name))
    return programs


@dataclass
class _RouteGroup:
    key: str          # 프로그램 id 꼬리표 ("" 면 클래스 하나가 곧 프로그램)
    title: str        # 업무명에 붙일 이름
    methods: list     # 이 그룹에 속한 메서드


def _route_groups(cls: JavaClass) -> list[_RouteGroup]:
    """라우트를 업무 프리픽스로 묶는다. 적으면 통째로 하나."""
    routed = [m for m in cls.methods if m.url_mappings]
    if not _is_python(cls) or len(routed) <= MAX_ROUTES_PER_PROGRAM:
        return [_RouteGroup(key="", title="", methods=[])]

    buckets: dict[str, list] = defaultdict(list)
    for method in cls.methods:
        buckets[_business_segment(method.url_mappings)].append(method)

    groups = [
        _RouteGroup(key=key, title=key, methods=methods)
        for key, methods in sorted(buckets.items())
        if key
    ]
    # 라우트가 없는 헬퍼 함수들은 첫 그룹에 얹어 둔다 (버려지지 않게)
    leftovers = buckets.get("", [])
    if leftovers and groups:
        groups[0].methods = groups[0].methods + leftovers
    elif leftovers:
        return [_RouteGroup(key="", title="", methods=[])]
    return groups


def _business_segment(url_mappings: list[str]) -> str:
    """"GET /api/v1/auth/login" → "auth". 껍데기 세그먼트는 건너뛴다."""
    for mapping in url_mappings:
        path = mapping.split(" ", 1)[-1]
        for seg in path.split("/"):
            if not seg or seg.startswith("{") or seg.startswith("<"):
                continue
            if seg.lower() in GENERIC_SEGMENTS:
                continue
            return seg
    return ""


def _program_from(
    cls: JavaClass,
    idx: Index,
    out_edges: dict[str, list[tuple[str, str]]],
    layers: list[dict[str, str]],
    covered: set[str],
    *,
    methods: list | None = None,
    suffix: str = "",
    title: str = "",
) -> Program:
    entry_methods = methods if methods else cls.methods
    classes: set[str] = set()
    sql_ids: set[str] = set()
    urls: list[str] = []
    service_ids: list[str] = []

    seen: set[str] = set()
    stack = [f"{cls.fqn}#{m.name}" for m in entry_methods]
    classes.add(cls.fqn)

    for m in entry_methods:
        for u in m.url_mappings:
            # 파이썬 라우트는 "GET /path" 형태로 이미 완성돼 있다
            urls.append(u if _is_python(cls) else _join_url(cls.class_mapping, u))
        if cls.kind == "controller" or not m.body:
            service_ids.append(f"{cls.name}.{m.name}")

    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for dst, kind in out_edges.get(node, []):
            if kind == "sql":
                sql_ids.add(dst)
                continue
            target_cls = dst.split("#")[0]
            if target_cls.startswith(FRAMEWORK_PREFIXES):
                continue
            if target_cls in idx.classes:
                classes.add(target_cls)
                stack.append(dst)
                # 인터페이스 → 구현체도 따라간다
                for impl in _implementations(target_cls, idx):
                    classes.add(impl)
                    stack.append(f"{impl}#{dst.split('#')[1]}")

    covered.update(classes)

    tables: set[str] = set()
    mappers: set[str] = set()
    for sid in sql_ids:
        st = idx.statements.get(sid)
        if not st:
            continue
        tables.update(st.tables)
        mappers.add(st.namespace)

    files = sorted({idx.classes[c].path for c in classes if c in idx.classes})
    files += sorted({idx.mappers[ns].path for ns in mappers if ns in idx.mappers})

    return Program(
        id=_slug(f"{cls.fqn}.{suffix}" if suffix else cls.fqn),
        name=f"{title} · {_title(cls)[:34]}" if title else _title(cls),
        layer=_layer_of(cls.path, layers),
        tier="backend",
        entry_fqn=cls.fqn,
        classes=sorted(classes),
        mappers=sorted(mappers),
        sql_ids=sorted(sql_ids),
        tables=sorted(tables),
        urls=sorted(set(urls)),
        service_ids=sorted(set(service_ids)),
        files=sorted(set(files)),
    )


def _implementations(iface_fqn: str, idx: Index) -> list[str]:
    iface = idx.classes.get(iface_fqn)
    if not iface or not iface.is_interface:
        return []
    return _implementations_of(iface, idx.classes)


def _implementations_of(iface: JavaClass, classes: dict[str, JavaClass]) -> list[str]:
    name = iface.name
    return [
        fqn
        for fqn, c in classes.items()
        if name in [_base_type(i) for i in c.implements]
    ]


def _join_url(base: str, path: str) -> str:
    if not base:
        return path
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def _slug(fqn: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fqn.lower()).strip("-")


def _title(cls: JavaClass) -> str:
    if _is_python(cls):
        return _py_title(cls)
    for doc, name in JAVADOC_RE.findall(cls.source or ""):
        if name != cls.name:
            continue
        for line in doc.splitlines():
            line = line.strip().lstrip("*").strip()
            if line and not line.startswith("@"):
                return line
    return cls.name


def _py_title(cls: JavaClass) -> str:
    """docstring 첫 줄을 업무명으로.

    클래스면 그 클래스의 docstring, 모듈이면 **파일 맨 앞** docstring 만 본다.
    그냥 첫 블록을 잡으면 모듈 docstring 이 없을 때 아무 함수의 설명이
    업무명이 돼, 서로 다른 프로그램 30개가 같은 이름을 달게 된다.
    """
    source = cls.source or ""
    marker = re.search(rf"^class\s+{re.escape(cls.name)}\b", source, re.M)
    if marker:
        match = PY_DOC_BLOCK_RE.search(source[marker.start():])
    else:
        match = PY_DOC_BLOCK_RE.search(source)
        # 모듈 docstring 은 코드보다 앞에 있어야 한다
        if match and PY_CODE_START_RE.search(source[: match.start()]):
            match = None
    if match:
        for line in match.group(2).splitlines():
            line = line.strip()
            if line:
                return line[:60]
    # docstring 이 없으면 경로로 구분한다. app.py 가 여러 디렉터리에 있는 일이
    # 흔해서, 모듈명만 쓰면 서로 다른 프로그램이 같은 이름으로 보인다.
    if not marker:
        parts = [p for p in cls.path.rsplit("/", 2) if p][:-1]
        stem = cls.path.rsplit("/", 1)[-1].removesuffix(".py")
        return "/".join([*parts[-1:], stem]) if parts else stem
    return cls.name


def _layer_of(path: str, layers: list[dict[str, str]]) -> str:
    norm = path.replace("\\", "/")
    for layer in layers:
        pattern = layer.get("match", "")
        if not pattern:
            continue
        if fnmatch.fnmatch(norm, pattern) or fnmatch.fnmatch("/" + norm, pattern):
            return layer.get("name", "기타")
    return "기타"


# --------------------------------------------------------------------------- #
# 테이블 / 영향도
# --------------------------------------------------------------------------- #
def _build_tables(idx: Index) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"statements": [], "programs": [], "crud": []}
    )
    for sid, st in idx.statements.items():
        for table, op in st.crud:
            entry = out[table]
            if sid not in entry["statements"]:
                entry["statements"].append(sid)
            if op not in entry["crud"]:
                entry["crud"].append(op)
    for prog in idx.programs:
        for table in prog.tables:
            if prog.id not in out[table]["programs"]:
                out[table]["programs"].append(prog.id)
    for entry in out.values():
        entry["statements"].sort()
        entry["programs"].sort()
        entry["crud"].sort()
    return dict(out)


def impact_of(idx: Index, program_id: str) -> dict[str, Any]:
    """이 프로그램을 고쳤을 때 같은 테이블을 쓰는 다른 프로그램."""
    prog = next((p for p in idx.programs if p.id == program_id), None)
    if not prog:
        return {"tables": [], "affected": []}

    affected: dict[str, dict[str, Any]] = {}
    for table in prog.tables:
        for other_id in idx.tables.get(table, {}).get("programs", []):
            if other_id == program_id:
                continue
            other = next((p for p in idx.programs if p.id == other_id), None)
            if not other:
                continue
            row = affected.setdefault(
                other_id, {"id": other_id, "name": other.name, "layer": other.layer, "tables": []}
            )
            if table not in row["tables"]:
                row["tables"].append(table)

    return {
        "tables": prog.tables,
        "affected": sorted(affected.values(), key=lambda r: -len(r["tables"])),
    }
