"""LLMWiki 온톨로지 — 확정 스키마 v1.0.0.

이 파일이 스키마의 **단일 원본(single source of truth)** 이다.
문서(`design/온톨로지-스키마.md`)는 여기서 내보낸 내용을 설명할 뿐이고,
`llmwiki ontology validate` 가 실제 산출물이 이 스키마를 지키는지 검사한다.

스키마를 문서로만 두면 코드가 먼저 움직이고 문서가 낡는다 — 이 제품이 풀려는
문제와 똑같은 실패다. 그래서 스키마를 코드로 두고 테스트로 고정한다.

핵심 개념 세 가지
-----------------
1) 노드/엣지 타입은 닫혀 있다. 여기 없는 종류는 산출물에 나올 수 없다.
2) 모든 노드·엣지는 식별자 규칙(`id_parts`)이 정해져 있어 재실행해도 같은 ID 가 나온다.
   → 두 시점의 그래프를 비교(diff)해 "무엇이 바뀌었나"를 계산할 수 있다.
3) 모든 사실에는 `derivation` 이 붙는다: static(파서) / derived(계산) / llm(서술).
   무엇이 소스에서 나온 사실이고 무엇이 모델이 쓴 말인지 스키마 레벨에서 갈린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

ONTOLOGY_VERSION = "1.0.0"

#: static  — 파서가 소스에서 직접 읽은 사실 (근거: 파일·라인)
#: derived — 사실들로부터 기계적으로 계산한 것 (영향도, CRUD 매트릭스)
#: llm     — 모델이 쓴 서술 (문서 본문)
Derivation = Literal["static", "derived", "llm"]

DERIVATIONS: tuple[str, ...] = ("static", "derived", "llm")

CRUD_OPS: tuple[str, ...] = ("C", "R", "U", "D")

#: JavaClass.kind 로 쓰이는 값의 닫힌 집합
TYPE_KINDS: tuple[str, ...] = (
    "controller", "service", "serviceimpl", "dao", "mapper", "vo", "util", "unknown",
)

#: SqlStatement.kind 로 쓰이는 값의 닫힌 집합
STATEMENT_KINDS: tuple[str, ...] = ("select", "insert", "update", "delete")


# --------------------------------------------------------------------------- #
# 스키마 정의
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NodeType:
    name: str
    prefix: str            # ID 접두어
    ko: str
    en: str
    id_parts: tuple[str, ...]   # ID 를 구성하는 속성 (순서 고정)
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    derivation: Derivation = "static"
    note: str = ""

    @property
    def properties(self) -> tuple[str, ...]:
        return self.required + self.optional


@dataclass(frozen=True)
class EdgeType:
    name: str
    ko: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    cardinality: str       # 1:1 | 1:N | N:1 | N:M
    derivation: Derivation = "static"
    properties: tuple[str, ...] = ()
    note: str = ""


NODE_TYPES: dict[str, NodeType] = {
    n.name: n
    for n in (
        NodeType(
            name="Project", prefix="prj", ko="프로젝트", en="Project",
            id_parts=("project_id",),
            required=("project_id", "name"),
            optional=("roots", "parsed_at", "counts"),
            note="분석 대상 시스템 하나. 워크스페이스에 등록된 단위.",
        ),
        NodeType(
            name="Layer", prefix="lyr", ko="계층", en="Layer",
            id_parts=("project_id", "name"),
            required=("project_id", "name"),
            note="기관계 / 채널계 / 공통 … config.yaml 의 project.layers 로 정의한다.",
        ),
        NodeType(
            name="SourceFile", prefix="file", ko="소스 파일", en="Source file",
            id_parts=("project_id", "path"),
            required=("project_id", "path"),
            optional=("language",),
            note="source_roots 기준 상대 경로. 소스 브라우저가 여는 단위.",
        ),
        NodeType(
            name="Type", prefix="type", ko="타입(클래스/인터페이스)", en="Type",
            id_parts=("project_id", "fqn"),
            required=("project_id", "fqn", "name", "package", "kind", "is_interface"),
            optional=("annotations", "extends", "implements", "path", "class_mapping"),
            note=f"kind 는 {TYPE_KINDS} 중 하나.",
        ),
        NodeType(
            name="Operation", prefix="op", ko="오퍼레이션(메서드)", en="Operation",
            id_parts=("project_id", "fqn", "method"),
            required=("project_id", "fqn", "method"),
            optional=("return_type", "params", "annotations", "line_start", "line_end"),
            note="v1.0 은 오버로드를 구분하지 않는다(같은 이름 = 같은 노드). 한계로 명시.",
        ),
        NodeType(
            name="Endpoint", prefix="ep", ko="호출 엔드포인트", en="Endpoint",
            id_parts=("project_id", "url"),
            required=("project_id", "url"),
            optional=("http_methods",),
            note="클래스 @RequestMapping 과 메서드 매핑을 합친 최종 URL.",
        ),
        NodeType(
            name="Mapper", prefix="mapper", ko="매퍼", en="Mapper",
            id_parts=("project_id", "namespace"),
            required=("project_id", "namespace"),
            optional=("path",),
            note="MyBatis Mapper XML 의 namespace.",
        ),
        NodeType(
            name="SqlStatement", prefix="sql", ko="SQL 문", en="SQL statement",
            id_parts=("project_id", "full_id"),
            required=("project_id", "full_id", "namespace", "statement_id", "kind"),
            optional=("sql", "params", "parameter_type", "result_type", "path", "line"),
            note=f"full_id = namespace + '.' + statement_id. kind 는 {STATEMENT_KINDS}.",
        ),
        NodeType(
            name="Table", prefix="tbl", ko="테이블", en="Table",
            id_parts=("project_id", "name"),
            required=("project_id", "name"),
            note="이름은 항상 대문자로 정규화한다. 컬럼은 v1.0 범위 밖.",
        ),
        NodeType(
            name="Program", prefix="prog", ko="프로그램(산출물 단위)", en="Program",
            id_parts=("project_id", "slug"),
            required=("project_id", "slug", "name", "layer", "tier", "entry_fqn"),
            derivation="derived",
            note="명세서 1건에 대응. 보통 컨트롤러 1개에서 도출한다.",
        ),
        NodeType(
            name="Document", prefix="doc", ko="명세서", en="Document",
            id_parts=("project_id", "slug", "language"),
            required=("project_id", "slug", "language"),
            optional=("generator", "generated_at", "source_hash"),
            derivation="llm",
            note="본문 서술은 llm, 부록(흐름도·CRUD·SQL·영향도)은 static/derived 다.",
        ),
    )
}

EDGE_TYPES: dict[str, EdgeType] = {
    e.name: e
    for e in (
        EdgeType("belongsTo", "소속", ("Type", "SourceFile", "Mapper", "Table", "Program", "Layer"),
                 ("Project",), "N:1"),
        EdgeType("declaredIn", "선언 위치", ("Type",), ("SourceFile",), "N:1"),
        EdgeType("declares", "메서드 보유", ("Type",), ("Operation",), "1:N"),
        EdgeType("extendsType", "상속", ("Type",), ("Type",), "N:1"),
        EdgeType("implementsType", "인터페이스 구현", ("Type",), ("Type",), "N:M"),
        EdgeType("implementsOperation", "메서드 구현", ("Operation",), ("Operation",), "N:M",
                 note="인터페이스 메서드 → 구현체 메서드. 흐름도에서 점선."),
        EdgeType("calls", "호출", ("Operation",), ("Operation",), "N:M",
                 note="수신 변수의 타입을 필드·파라미터·지역변수 선언으로 해석해 잇는다."),
        EdgeType("executes", "SQL 실행", ("Operation",), ("SqlStatement",), "N:M",
                 note="Mapper 인터페이스 메서드명 매칭 또는 sqlSession 직접 호출."),
        EdgeType("definedIn", "SQL 정의 위치", ("SqlStatement",), ("Mapper",), "N:1"),
        EdgeType("accesses", "테이블 접근", ("SqlStatement",), ("Table",), "N:M",
                 properties=("crud",),
                 note=f"crud 는 {CRUD_OPS} 중 하나. 같은 쌍에 여러 op 가 올 수 있다."),
        EdgeType("exposes", "URL 노출", ("Operation",), ("Endpoint",), "1:N"),
        EdgeType("hasEntry", "진입 클래스", ("Program",), ("Type",), "1:1", derivation="derived"),
        EdgeType("involves", "관련 클래스", ("Program",), ("Type",), "N:M", derivation="derived"),
        EdgeType("runs", "사용 SQL", ("Program",), ("SqlStatement",), "N:M", derivation="derived"),
        EdgeType("touches", "접근 테이블", ("Program",), ("Table",), "N:M", derivation="derived"),
        EdgeType("serves", "제공 엔드포인트", ("Program",), ("Endpoint",), "1:N", derivation="derived"),
        EdgeType("classifiedAs", "계층 분류", ("Program",), ("Layer",), "N:1", derivation="derived"),
        EdgeType("impacts", "영향", ("Program",), ("Program",), "N:M", derivation="derived",
                 properties=("via_tables",),
                 note="같은 테이블을 쓰는 프로그램. 대칭 관계지만 양방향으로 저장한다."),
        EdgeType("documents", "명세 대상", ("Document",), ("Program",), "1:1", derivation="llm"),
    )
}

#: v1.1 확장 예약 — 아직 산출물에 나오지 않는다. 선언만 해 두어 나중에
#: 스키마가 흔들리지 않게 한다. (To-Be 설계 사이클: 요구사항 → 설계 → 테스트)
RESERVED_V1_1: dict[str, str] = {
    "Requirement": "요구사항 항목 (입력 폼에서 수집)",
    "ScreenSpec": "화면 설계 항목",
    "TestCase": "요구사항에서 파생한 테스트 케이스",
    "Column": "테이블 컬럼",
    "realizes": "Program → Requirement",
    "verifies": "TestCase → Requirement",
    "hasColumn": "Table → Column",
}


# --------------------------------------------------------------------------- #
# 식별자
# --------------------------------------------------------------------------- #
def node_id(node_type: str, **parts: Any) -> str:
    """스키마의 id_parts 순서대로 ID 를 만든다. 재실행해도 값이 같아야 한다."""
    spec = NODE_TYPES.get(node_type)
    if spec is None:
        raise KeyError(f"알 수 없는 노드 타입: {node_type}")
    missing = [p for p in spec.id_parts if parts.get(p) in (None, "")]
    if missing:
        raise ValueError(f"{node_type} ID 에 필요한 값 누락: {missing}")
    body = "/".join(str(parts[p]) for p in spec.id_parts)
    return f"{spec.prefix}:{body}"


# --------------------------------------------------------------------------- #
# 검증
# --------------------------------------------------------------------------- #
@dataclass
class Issue:
    level: str      # error | warning
    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - 표시용
        return f"[{self.level}] {self.code}: {self.message}"


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, level: str, code: str, message: str) -> None:
        self.issues.append(Issue(level, code, message))


def validate_index(idx: Any) -> ValidationResult:
    """`llmwiki parse` 결과(Index)가 온톨로지를 지키는지 검사한다.

    스키마를 코드로 둔 이유가 여기다 — 파서를 고치다 규칙을 깨면 테스트가 잡는다.
    """
    r = ValidationResult()

    # --- Type ---
    for fqn, cls in idx.classes.items():
        if cls.kind not in TYPE_KINDS:
            r.add("error", "type.kind", f"{fqn}: 정의되지 않은 kind '{cls.kind}'")
        expected = f"{cls.package}.{cls.name}" if cls.package else cls.name
        if fqn != expected:
            r.add("error", "type.id", f"{fqn}: FQN 이 package+name({expected}) 과 다르다")

    # --- SqlStatement ---
    for sid, st in idx.statements.items():
        if st.kind not in STATEMENT_KINDS:
            r.add("error", "sql.kind", f"{sid}: 정의되지 않은 kind '{st.kind}'")
        if sid != f"{st.namespace}.{st.id}":
            r.add("error", "sql.id", f"{sid}: full_id 규칙(namespace.id) 위반")
        if st.namespace not in idx.mappers:
            r.add("error", "sql.definedIn", f"{sid}: namespace 에 해당하는 Mapper 없음")
        for pair in st.crud:
            if len(pair) != 2:
                r.add("error", "accesses.shape", f"{sid}: crud 항목은 [table, op] 이어야 한다")
                continue
            table, op = pair
            if op not in CRUD_OPS:
                r.add("error", "accesses.crud", f"{sid}: 알 수 없는 CRUD '{op}'")
            if table != table.upper():
                r.add("error", "table.case", f"{sid}: 테이블명 '{table}' 이 대문자가 아니다")
            if table not in st.tables:
                r.add("warning", "accesses.table", f"{sid}: crud 의 {table} 이 tables 에 없다")

    # --- 엣지 ---
    known_ops = {f"{fqn}#{m.name}" for fqn, c in idx.classes.items() for m in c.methods}
    edge_kind_map = {"call": "calls", "impl": "implementsOperation", "sql": "executes"}
    for src, dst, kind in idx.edges:
        if kind not in edge_kind_map:
            r.add("error", "edge.kind", f"정의되지 않은 엣지 종류 '{kind}' ({src} → {dst})")
            continue
        if src not in known_ops:
            r.add("error", "edge.domain", f"{kind}: 출발 오퍼레이션을 찾을 수 없음 — {src}")
        if kind == "sql":
            if dst not in idx.statements:
                r.add("error", "edge.range", f"executes: SQL 문을 찾을 수 없음 — {dst}")
        elif dst not in known_ops:
            r.add("error", "edge.range", f"{kind}: 도착 오퍼레이션을 찾을 수 없음 — {dst}")

    # --- Program ---
    seen_slugs: set[str] = set()
    for prog in idx.programs:
        if prog.id in seen_slugs:
            r.add("error", "program.id", f"프로그램 ID 중복: {prog.id}")
        seen_slugs.add(prog.id)
        if prog.entry_fqn not in idx.classes:
            r.add("error", "hasEntry", f"{prog.id}: 진입 클래스 {prog.entry_fqn} 없음")
        for fqn in prog.classes:
            if fqn not in idx.classes:
                r.add("error", "involves", f"{prog.id}: 클래스 {fqn} 없음")
        for sid in prog.sql_ids:
            if sid not in idx.statements:
                r.add("error", "runs", f"{prog.id}: SQL {sid} 없음")
        for table in prog.tables:
            if table != table.upper():
                r.add("error", "table.case", f"{prog.id}: 테이블명 '{table}' 이 대문자가 아니다")

    # --- Table 역인덱스 ---
    for name, info in idx.tables.items():
        if name != name.upper():
            r.add("error", "table.case", f"테이블 '{name}' 이 대문자가 아니다")
        for op in info.get("crud", []):
            if op not in CRUD_OPS:
                r.add("error", "accesses.crud", f"{name}: 알 수 없는 CRUD '{op}'")

    return r


# --------------------------------------------------------------------------- #
# 그래프 내보내기
# --------------------------------------------------------------------------- #
def build_graph(
    idx: Any,
    *,
    project_id: str = "default",
    documents: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Index → 온톨로지 그래프(노드/엣지 목록).

    그래프 DB 적재, 다른 도구 연계, 두 시점 비교(diff)의 입력으로 쓴다.
    """
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(ntype: str, props: dict[str, Any]) -> str:
        nid = node_id(ntype, **props)
        if nid not in nodes:
            nodes[nid] = {
                "id": nid,
                "type": ntype,
                "derivation": NODE_TYPES[ntype].derivation,
                **props,
            }
        return nid

    def add_edge(etype: str, src: str, dst: str, **props: Any) -> None:
        edges.append(
            {
                "type": etype,
                "source": src,
                "target": dst,
                "derivation": EDGE_TYPES[etype].derivation,
                **props,
            }
        )

    prj = add_node("Project", {"project_id": project_id, "name": idx.project})

    # 타입 · 파일 · 오퍼레이션
    op_ids: dict[str, str] = {}
    for fqn, cls in idx.classes.items():
        tid = add_node("Type", {
            "project_id": project_id, "fqn": fqn, "name": cls.name,
            "package": cls.package, "kind": cls.kind, "is_interface": cls.is_interface,
            "path": cls.path,
        })
        add_edge("belongsTo", tid, prj)
        if cls.path:
            fid = add_node("SourceFile", {
                "project_id": project_id, "path": cls.path,
                "language": _language_of(cls.path),
            })
            add_edge("belongsTo", fid, prj)
            add_edge("declaredIn", tid, fid)
        for iface in cls.implements:
            target = _resolve_simple(iface, idx.classes)
            if target:
                add_edge("implementsType", tid, node_id(
                    "Type", project_id=project_id, fqn=target))
        if cls.extends:
            target = _resolve_simple(cls.extends, idx.classes)
            if target:
                add_edge("extendsType", tid, node_id(
                    "Type", project_id=project_id, fqn=target))

        for m in cls.methods:
            oid = add_node("Operation", {
                "project_id": project_id, "fqn": fqn, "method": m.name,
                "return_type": m.return_type, "line_start": m.line_start,
                "line_end": m.line_end,
            })
            op_ids[f"{fqn}#{m.name}"] = oid
            add_edge("declares", tid, oid)
            for url in m.url_mappings:
                full = _join_url(cls.class_mapping, url)
                eid = add_node("Endpoint", {"project_id": project_id, "url": full})
                add_edge("exposes", oid, eid)

    # 매퍼 · SQL · 테이블
    for ns, mapper in idx.mappers.items():
        mid = add_node("Mapper", {
            "project_id": project_id, "namespace": ns, "path": mapper.path})
        add_edge("belongsTo", mid, prj)

    for sid, st in idx.statements.items():
        sql_node = add_node("SqlStatement", {
            "project_id": project_id, "full_id": sid, "namespace": st.namespace,
            "statement_id": st.id, "kind": st.kind, "path": st.path, "line": st.line,
        })
        if st.namespace in idx.mappers:
            add_edge("definedIn", sql_node,
                     node_id("Mapper", project_id=project_id, namespace=st.namespace))
        for table, op in st.crud:
            tbl = add_node("Table", {"project_id": project_id, "name": table})
            add_edge("belongsTo", tbl, prj)
            add_edge("accesses", sql_node, tbl, crud=op)

    # 호출 관계
    edge_kind_map = {"call": "calls", "impl": "implementsOperation", "sql": "executes"}
    for src, dst, kind in idx.edges:
        etype = edge_kind_map.get(kind)
        if not etype or src not in op_ids:
            continue
        if etype == "executes":
            if dst in idx.statements:
                add_edge(etype, op_ids[src],
                         node_id("SqlStatement", project_id=project_id, full_id=dst))
        elif dst in op_ids:
            add_edge(etype, op_ids[src], op_ids[dst])

    # 프로그램 · 계층
    by_table: dict[str, set[str]] = {}
    for prog in idx.programs:
        pid = add_node("Program", {
            "project_id": project_id, "slug": prog.id, "name": prog.name,
            "layer": prog.layer, "tier": prog.tier, "entry_fqn": prog.entry_fqn,
        })
        add_edge("belongsTo", pid, prj)
        lid = add_node("Layer", {"project_id": project_id, "name": prog.layer})
        add_edge("classifiedAs", pid, lid)
        if prog.entry_fqn in idx.classes:
            add_edge("hasEntry", pid,
                     node_id("Type", project_id=project_id, fqn=prog.entry_fqn))
        for fqn in prog.classes:
            if fqn in idx.classes:
                add_edge("involves", pid,
                         node_id("Type", project_id=project_id, fqn=fqn))
        for s in prog.sql_ids:
            if s in idx.statements:
                add_edge("runs", pid,
                         node_id("SqlStatement", project_id=project_id, full_id=s))
        for table in prog.tables:
            add_edge("touches", pid, node_id("Table", project_id=project_id, name=table))
            by_table.setdefault(table, set()).add(pid)
        for url in prog.urls:
            add_edge("serves", pid, node_id("Endpoint", project_id=project_id, url=url))

    # 영향도 (파생) — 같은 테이블을 쓰는 프로그램 쌍
    pair_tables: dict[tuple[str, str], list[str]] = {}
    for table, pids in by_table.items():
        for a in pids:
            for b in pids:
                if a != b:
                    pair_tables.setdefault((a, b), []).append(table)
    for (a, b), tables in sorted(pair_tables.items()):
        add_edge("impacts", a, b, via_tables=sorted(tables))

    # 명세서
    for meta in documents or []:
        slug, lang = meta.get("id"), meta.get("language", "ko")
        if not slug:
            continue
        did = add_node("Document", {
            "project_id": project_id, "slug": slug, "language": lang,
            "generator": meta.get("generator", ""),
            "generated_at": meta.get("generated_at", ""),
            "source_hash": meta.get("source_hash", ""),
        })
        add_edge("documents", did,
                 node_id("Program", project_id=project_id, slug=slug))

    return {
        "ontology": ONTOLOGY_VERSION,
        "project": {"id": project_id, "name": idx.project},
        "nodes": list(nodes.values()),
        "edges": edges,
    }


def schema_dict() -> dict[str, Any]:
    """스키마 자체를 기계가 읽을 수 있는 형태로 내보낸다."""
    return {
        "ontology": ONTOLOGY_VERSION,
        "derivations": list(DERIVATIONS),
        "enums": {
            "type_kind": list(TYPE_KINDS),
            "statement_kind": list(STATEMENT_KINDS),
            "crud": list(CRUD_OPS),
        },
        "nodes": {
            n.name: {
                "prefix": n.prefix, "ko": n.ko, "en": n.en,
                "id_parts": list(n.id_parts),
                "required": list(n.required), "optional": list(n.optional),
                "derivation": n.derivation, "note": n.note,
            }
            for n in NODE_TYPES.values()
        },
        "edges": {
            e.name: {
                "ko": e.ko, "domain": list(e.domain), "range": list(e.range),
                "cardinality": e.cardinality, "derivation": e.derivation,
                "properties": list(e.properties), "note": e.note,
            }
            for e in EDGE_TYPES.values()
        },
        "reserved_v1_1": RESERVED_V1_1,
    }


# --------------------------------------------------------------------------- #
_LANG_BY_SUFFIX = {
    ".java": "java", ".xml": "xml", ".sql": "sql", ".properties": "properties",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".jsp": "jsp",
}


def _language_of(path: str) -> str:
    for suffix, lang in _LANG_BY_SUFFIX.items():
        if path.endswith(suffix):
            return lang
    return "text"


def _resolve_simple(type_name: str, classes: dict[str, Any]) -> str | None:
    """`CustomerService` 또는 `com.gng...CustomerService` → FQN."""
    base = type_name.split("<")[0].strip().split(".")[-1]
    for fqn, cls in classes.items():
        if cls.name == base:
            return fqn
    return None


def _join_url(base: str, path: str) -> str:
    if not base:
        return path
    return f"{base.rstrip('/')}/{path.lstrip('/')}"
