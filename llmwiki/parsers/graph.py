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

    simple = _simple_name_map(idx.classes)
    edges: set[tuple[str, str, str]] = set()

    for fqn, cls in idx.classes.items():
        var_types = _var_types(cls, simple)
        for method in cls.methods:
            src = f"{fqn}#{method.name}"
            local = dict(var_types)
            local.update(_local_var_types(method, simple))
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


def _local_var_types(method, simple: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ptype, pname in method.params:
        target = simple.get(_base_type(ptype))
        if target and pname:
            out[pname] = target
    for mtype, mname in LOCAL_VAR_RE.findall(method.body or ""):
        target = simple.get(_base_type(mtype))
        if target:
            out[mname] = target
    return out


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
        programs.append(_program_from(cls, idx, out_edges, layers, covered))

    # 컨트롤러에 잡히지 않은 서비스(배치/내부 모듈)도 프로그램으로
    for cls in idx.classes.values():
        if cls.kind not in ("service", "serviceimpl"):
            continue
        if cls.fqn in covered:
            continue
        programs.append(_program_from(cls, idx, out_edges, layers, covered))

    programs.sort(key=lambda p: (p.layer, p.name))
    return programs


def _program_from(
    cls: JavaClass,
    idx: Index,
    out_edges: dict[str, list[tuple[str, str]]],
    layers: list[dict[str, str]],
    covered: set[str],
) -> Program:
    classes: set[str] = set()
    sql_ids: set[str] = set()
    urls: list[str] = []
    service_ids: list[str] = []

    seen: set[str] = set()
    stack = [f"{cls.fqn}#{m.name}" for m in cls.methods]
    classes.add(cls.fqn)

    for m in cls.methods:
        for u in m.url_mappings:
            urls.append(_join_url(cls.class_mapping, u))
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
        id=_slug(cls.fqn),
        name=_title(cls),
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
    for doc, name in JAVADOC_RE.findall(cls.source or ""):
        if name != cls.name:
            continue
        for line in doc.splitlines():
            line = line.strip().lstrip("*").strip()
            if line and not line.startswith("@"):
                return line
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
