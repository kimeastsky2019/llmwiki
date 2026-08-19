"""문서 지식베이스 온톨로지 — 확정 스키마 v0.1.0.

`llmwiki/ontology.py`(소스 코드)와 `llmwiki/compliance/ontology.py`(규제)에 이어
세 번째 그래프다. 셋 다 같은 규율을 따른다 — **스키마는 코드가 원본이고 테스트가
고정한다.** 문서로만 두면 코드가 먼저 움직이고 문서가 낡는다.

`build_graph()` 는 다른 두 그래프와 **같은 노드/엣지 목록 형식**을 낸다. 그래서
Neo4j·Memgraph 적재, RDF 변환, Fuseki 업로드가 모두 이 하나에서 출발한다.

원칙
----
1) 타입 집합은 닫혀 있다. 여기 없는 종류는 산출물에 나올 수 없다.
2) 모든 사실에 ``derivation`` 이 붙는다: measured / documented / assumed / computed.
   PDF 에는 `static`(파서가 읽은 코드)이 존재할 수 없다. 출처가 아니라 **근거 강도**를
   기록해야 감리에서 "어디까지 믿을 수 있나" 에 답할 수 있다.
3) 문서에서 온 값은 반드시 `EvidenceSpan` 을 갖는다 — 근거 없는 사실 금지.

★ 단일 실패 지점 — ID 에 좌표를 넣지 마라
----------------------------------------
규제 그래프에서 "조문 번호를 ID 로 쓰면 개정 때 전부 깨진다" 가 단일 실패 지점인
것과 **같은 함정**이 여기 있다. PDF 파서를 고치면 셀 병합·회전 도면 해석이 달라져
bbox 가 밀린다. 좌표를 ID 로 쓴 그래프는 그 순간 **전부** 끊긴다. 초기에 놓치면
파서를 한 번도 개선할 수 없다.

그래서 ID 는 의미 기반이고, 좌표는 `EvidenceSpan` 의 속성으로만 산다.
`validate_graph()` 와 `test_node_ids_contain_no_coordinates` 가 이 결정을 지킨다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from . import taxonomy

KB_ONTOLOGY_VERSION = "0.1.0"

#: measured   — 현장 계측기 실측 (25.7 kW)
#: documented — 청구서·명판·계약·법정계수 (1,897원/kg)
#: assumed    — 가정·설계치·카탈로그 (부하율 60%)
#: computed   — 위 셋에서 기계 계산 (3,989,376 kWh)
Derivation = Literal["measured", "documented", "assumed", "computed"]

DERIVATIONS: tuple[str, ...] = ("measured", "documented", "assumed", "computed")

#: 감리에서 검토 대상이 되는 근거 등급. `assumed` 만 사람이 다시 봐야 한다.
REVIEWABLE_DERIVATIONS: tuple[str, ...] = ("assumed",)


@dataclass(frozen=True)
class NodeType:
    name: str
    prefix: str
    ko: str
    en: str
    id_parts: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    derivation: Derivation = "documented"
    #: 문서에서 온 사실인가 — True 면 EvidenceSpan 연결이 필수다
    requires_span: bool = False
    note: str = ""


@dataclass(frozen=True)
class EdgeType:
    name: str
    ko: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    cardinality: str
    derivation: Derivation = "documented"
    note: str = ""


NODE_TYPES: dict[str, NodeType] = {
    n.name: n
    for n in (
        NodeType(
            name="Diagnosis", prefix="dgn", ko="진단(문서)", en="Diagnosis",
            id_parts=("diagnosis_id",),
            required=("name", "doc_hash", "pages", "sector"),
            optional=("sector_name", "unit_basis", "sector_confidence", "sector_needs_review"),
            note="문서 1건 = 그래프 1개의 뿌리. doc_hash 가 같은 파일임을 보증한다.",
        ),
        NodeType(
            name="Sector", prefix="sec", ko="업종", en="Sector",
            id_parts=("sector",),
            required=("name", "ksic", "unit_basis"),
            note=f"taxonomy 의 닫힌 집합 {len(taxonomy.SECTOR_CODES)}종 중 하나.",
        ),
        NodeType(
            name="EvidenceSpan", prefix="span", ko="근거 위치", en="Evidence span",
            id_parts=("diagnosis_id", "page", "table_idx"),
            required=("page",),
            optional=("table_idx", "caption", "shape"),
            note="좌표가 사는 유일한 곳. ID 에는 페이지·표 번호만 들어가고 bbox 는 속성이다.",
        ),
        NodeType(
            name="Quantity", prefix="qty", ko="수치", en="Quantity",
            id_parts=("diagnosis_id", "metric", "cell"),
            required=("value", "unit", "dimension"),
            optional=("label", "raw", "page", "cell"),
            requires_span=True,
            note="단위가 숫자에 붙어 있을 때만 승격한다. 근거가 약한 값을 올리면 검산이 오염된다.",
        ),
        NodeType(
            name="Equipment", prefix="eq", ko="설비", en="Equipment",
            id_parts=("diagnosis_id", "name"),
            required=("name",),
            optional=("mentions", "sector"),
            note="업종 프로파일의 key_equipment 를 문서에서 찾은 것. 언급 횟수만 센다.",
        ),
        NodeType(
            name="Finding", prefix="fnd", ko="지적사항", en="Finding",
            id_parts=("diagnosis_id", "rule"),
            required=("rule", "severity", "title"),
            optional=("detail", "law", "article", "resolution"),
            derivation="computed",
            note="룰이 만든다. resolution 은 사람만 채운다 — 판정과 확정을 가르는 자리다.",
        ),
        NodeType(
            name="Channel", prefix="chan", ko="채널", en="Channel",
            id_parts=("diagnosis_id", "channel"),
            required=("channel", "count"),
            derivation="computed",
            note="글·표·그림 각 채널의 청크 수. 파싱이 무엇을 얼마나 건졌는지 그래프에 남긴다.",
        ),
    )
}

EDGE_TYPES: dict[str, EdgeType] = {
    e.name: e
    for e in (
        EdgeType("classifiedAs", "업종 분류", ("Diagnosis",), ("Sector",), "N:1",
                 derivation="computed",
                 note="분류 방법·신뢰도를 엣지 속성으로 들고 간다. 확정 여부는 Diagnosis 가 갖는다."),
        EdgeType("evidencedBy", "근거", ("Diagnosis", "Quantity"), ("EvidenceSpan",), "N:M",
                 note="Quantity 는 이 엣지가 없으면 그래프에 있을 수 없다."),
        EdgeType("belongsTo", "소속", ("Quantity", "Equipment"), ("Diagnosis",), "N:1"),
        EdgeType("installedAt", "설치 위치", ("Equipment",), ("Diagnosis",), "N:1"),
        EdgeType("flags", "지적", ("Finding",), ("Diagnosis",), "N:1", derivation="computed"),
        EdgeType("hasChannel", "채널 보유", ("Diagnosis",), ("Channel",), "1:N",
                 derivation="computed"),
    )
}

#: v0.2 확장 예약 — 아직 산출물에 나오지 않는다. 선언만 해 두어 나중에 스키마가
#: 흔들리지 않게 한다. `computedFrom` 이 가장 큰 미완이다: 값들 사이의 수식
#: (연간사용량 = 정격 × 시간 × 부하율)이 그래프에 들어와야 산술 검산 룰이 돈다.
RESERVED_V0_2: dict[str, str] = {
    "Formula": "수식 (연간사용량 = 정격 × 시간 × 부하율)",
    "MassBalance": "물질수지 (함수율 기반 건조 열량 검증)",
    "Nameplate": "명판 (사진 OCR 로 읽은 설비 제원)",
    "computedFrom": "Quantity → Quantity (계산 체인)",
    "measuredAt": "Quantity → Equipment",
}

NUM = re.compile(r"-?\d[\d,]*\.?\d*")

#: 단위 목록. 긴 것부터 두어야 'kWh/y' 가 'kWh' 로 잘리지 않는다.
_UNITS: tuple[str, ...] = (
    "kWh/y", "kWh", "kW", "toe/MWh", "tCO2eq/MWh", "tCO₂eq/MWh", "tCO2eq", "tCO₂eq",
    "toe", "MWh", "t/h", "kg/h", "㎥/min", "원/kWh", "원/kg", "천원", "원",
    "h/y", "h/d", "mmAq", "kg/㎠", "kcal/kg", "톤/일", "t/일", "㎡", "%", "대", "년",
)

#: **숫자에 붙어 있는** 단위만 인정한다. 셀 전체에서 단위를 따로 찾으면 '남원시'의
#: '원'을 화폐로, '2015년 9월'의 '년'을 기간으로 읽는다. 단위 뒤에 한글이
#: 이어지면(원형/대수/년도) 단위가 아니다.
QTY = re.compile(
    r"(-?\d[\d,]*\.?\d*)\s*[\(\[]?\s*(" + "|".join(re.escape(u) for u in _UNITS) + r")"
    r"(?![가-힣A-Za-z0-9])"
)

#: 단위 → 차원. 차원이 있어야 수식 양변 검산이 가능하다.
DIMENSION: dict[str, str] = {
    "kW": "power", "kWh": "energy", "kWh/y": "energy", "MWh": "energy",
    "toe": "energy_toe", "tCO2eq": "ghg", "tCO₂eq": "ghg",
    "kg": "fuel_mass", "kg/h": "fuel_rate", "t/h": "steam_flow",
    "원": "cost", "천원": "cost", "원/kWh": "price", "원/kg": "price",
    "h/y": "time", "h/d": "time", "%": "ratio", "대": "count",
    "㎡": "area", "톤/일": "capacity", "t/일": "capacity",
    "㎥/min": "flow", "mmAq": "pressure", "kg/㎠": "pressure",
    "kcal/kg": "heating_value", "toe/MWh": "factor",
    "tCO2eq/MWh": "factor", "tCO₂eq/MWh": "factor",
    # 연도는 양이 아니라 식별자에 가깝다. 차원을 따로 두어 에너지 집계에서 배제한다.
    "년": "year",
}

#: 에너지·비용 집계와 검산에서 제외할 차원
NON_QUANTITY_DIMENSIONS = frozenset({"year", "unknown"})


def _slug(s: str, maxlen: int = 40) -> str:
    s = re.sub(r"\s+", "_", (s or "").strip())
    s = re.sub(r"[^\w가-힣._-]", "", s)
    return (s or "unnamed")[:maxlen]


def _num(s: str) -> float | None:
    m = NUM.search((s or "").replace(" ", ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_quantity(cell: str, header: str = "") -> tuple[float, str] | None:
    """셀에서 (값, 단위)를 뽑는다. 단위가 숫자에 붙어 있어야 인정한다.

    셀에 단위가 없으면 헤더의 단위를 빌려 쓴다 — ``용량(kW)`` 헤더 아래 ``22`` 같은
    표기가 실제 진단서에서 가장 흔한 형태다. 다만 이때도 셀은 순수한 숫자여야 한다.
    """
    if not cell:
        return None
    m = QTY.search(cell)
    if m:
        try:
            return float(m.group(1).replace(",", "")), m.group(2)
        except ValueError:
            return None

    bare = cell.strip().replace(" ", "")
    if not re.fullmatch(r"-?\d[\d,]*\.?\d*", bare):
        return None
    hm = re.search(r"[\(\[]\s*(" + "|".join(re.escape(u) for u in _UNITS) + r")\s*[\)\]]",
                   header or "")
    if not hm:
        return None
    try:
        return float(bare.replace(",", "")), hm.group(1)
    except ValueError:
        return None


def build_graph(doc, classification, coverage: dict,
                gate_report: dict | None = None,
                *, diagnosis_id: str | None = None) -> dict[str, Any]:
    """ParsedDocument → 온톨로지 그래프 (노드/엣지 목록)."""
    did = diagnosis_id or _slug(doc.filename.rsplit(".", 1)[0], 24) or doc.doc_hash
    sector = classification.sector
    prof = taxonomy.get(sector)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def add_node(**kw: Any) -> None:
        nodes.append(kw)

    def add_edge(type_: str, source: str, target: str, **kw: Any) -> None:
        edges.append({"type": type_, "source": source, "target": target, **kw})

    # --- Diagnosis (뿌리) -------------------------------------------------- #
    dgn = f"dgn:{did}"
    add_node(id=dgn, type="Diagnosis", derivation="documented",
             name=doc.filename, doc_hash=doc.doc_hash, pages=doc.n_pages,
             sector=sector, sector_name=prof.name, unit_basis=prof.unit_basis,
             sector_confidence=round(classification.confidence, 3),
             sector_needs_review=classification.needs_review)

    # --- Sector ------------------------------------------------------------ #
    sec = f"sec:{sector}"
    add_node(id=sec, type="Sector", derivation="documented",
             name=prof.name, ksic=prof.ksic, unit_basis=prof.unit_basis)
    add_edge("classifiedAs", dgn, sec, derivation="computed",
             method=classification.method, confidence=round(classification.confidence, 3))

    # --- EvidenceSpan + Quantity (표에서) ---------------------------------- #
    # 표 셀 하나하나가 후보지만, 값+단위가 함께 읽히는 셀만 승격한다.
    # 근거가 약한 것을 올리면 아래 모든 검산이 오염된다.
    qcount = 0
    for t in doc.tables:
        span_id = f"span:{did}/p{t.page}/tbl{t.idx}"
        add_node(id=span_id, type="EvidenceSpan", derivation="documented",
                 page=t.page, table_idx=t.idx, caption=t.caption, shape=list(t.shape))
        add_edge("evidencedBy", dgn, span_id, derivation="documented")

        for ri, row in enumerate(t.rows):
            label = next((c for c in row if c and not _num(c)), "")
            for ci, cell in enumerate(row):
                if not cell:
                    continue
                head = t.header[ci] if ci < len(t.header) else ""
                parsed = parse_quantity(cell, head)
                if parsed is None:
                    continue                     # 단위 없는 숫자는 올리지 않는다
                val, unit = parsed
                metric = _slug(f"{label}.{head or ci}", 48)
                qid = f"qty:{did}/{_slug(str(t.page))}_{t.idx}/{metric}_{ri}{ci}"
                add_node(id=qid, type="Quantity", derivation="documented",
                         value=val, unit=unit, dimension=DIMENSION.get(unit, "unknown"),
                         label=label or None, raw=cell,
                         page=t.page, cell=f"r{ri}c{ci}")
                add_edge("evidencedBy", qid, span_id, derivation="documented")
                add_edge("belongsTo", qid, dgn, derivation="documented")
                qcount += 1

    # --- Equipment (업종 프로파일의 주요 설비군을 문서에서 찾는다) ----------- #
    haystack = doc.searchable_text
    for eq in prof.key_equipment:
        n = len(re.findall(re.escape(eq), haystack))
        if not n:
            continue
        eid = f"eq:{did}/{_slug(eq, 20)}"
        add_node(id=eid, type="Equipment", derivation="documented",
                 name=eq, mentions=n, sector=sector)
        add_edge("installedAt", eid, dgn, derivation="documented")

    # --- 필수지표 커버리지 → Finding --------------------------------------- #
    for m in coverage.get("missing", []):
        fid = f"fnd:{did}/metric.missing#{_slug(m['code'], 30)}"
        add_node(id=fid, type="Finding", derivation="computed",
                 rule="metric.missing", severity="warning",
                 title=f"업종 필수지표 누락: {m['label']}",
                 detail=f"{prof.name} 진단서는 {m['label']}를 포함해야 한다.",
                 resolution=None)
        add_edge("flags", fid, dgn, derivation="computed")

    # --- 적재 게이트 → Finding --------------------------------------------- #
    if gate_report:
        for i, f in enumerate(gate_report.get("findings", [])):
            fid = f"fnd:{did}/{f['rule']}#{i}"
            add_node(id=fid, type="Finding", derivation="computed",
                     rule=f["rule"], severity=f["severity"],
                     law=f["law"], article=f["article"],
                     title=f["title"], detail=f["detail"],
                     resolution=f.get("resolution"))
            add_edge("flags", fid, dgn, derivation="computed")

    # --- 채널 통계 --------------------------------------------------------- #
    for ch, cnt in (("text", len(doc.text_blocks)), ("table", len(doc.tables)),
                    ("image", len(doc.images))):
        cid = f"chan:{did}/{ch}"
        add_node(id=cid, type="Channel", derivation="computed", channel=ch, count=cnt)
        add_edge("hasChannel", dgn, cid, derivation="computed")

    return {
        "ontology": KB_ONTOLOGY_VERSION,
        "diagnosis": {
            "id": did,
            "document": doc.filename,
            "doc_hash": doc.doc_hash,
            "sector": sector,
            "sector_name": prof.name,
        },
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "quantities": qcount,
            "findings": sum(1 for n in nodes if n["type"] == "Finding"),
            "by_type": _count(n["type"] for n in nodes),
            "by_derivation": _count(n.get("derivation", "-") for n in nodes),
        },
        "nodes": nodes,
        "edges": edges,
    }


def _count(it) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in it:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- #
# 검증 — 스키마를 코드로 둔 이유가 여기다
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


#: ID 에 좌표가 새어 들어왔는지 보는 패턴. bbox·x0 같은 이름과, 소수점 3자리 이상
#: 이어지는 값(=PDF 좌표)을 잡는다.
COORDINATE_IN_ID = re.compile(r"\bbbox\b|\bx0\b|\bx1\b|\btop\b|\bbottom\b|\d+\.\d{3,}")


def validate_graph(graph: dict[str, Any]) -> ValidationResult:
    """그래프가 온톨로지를 지키는지 검사한다.

    성능 검사가 아니라 **설계 결정을 지키는 검사**다. 누가 편의를 위해 ID 규칙을
    바꾸거나 근거 없는 값을 올리면 여기서 걸려야 한다.
    """
    r = ValidationResult()
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    by_id = {n.get("id", ""): n for n in nodes}

    if graph.get("ontology") != KB_ONTOLOGY_VERSION:
        r.add("warning", "ontology.version",
              f"그래프 버전({graph.get('ontology')})이 현재 스키마({KB_ONTOLOGY_VERSION})와 다르다")

    for n in nodes:
        nid, ntype = n.get("id", ""), n.get("type", "")
        spec = NODE_TYPES.get(ntype)
        if spec is None:
            r.add("error", "node.type", f"{nid}: 정의되지 않은 노드 타입 '{ntype}'")
            continue
        if not nid.startswith(f"{spec.prefix}:"):
            r.add("error", "node.id",
                  f"{nid}: {ntype} 의 ID 는 '{spec.prefix}:' 로 시작해야 한다")
        if COORDINATE_IN_ID.search(nid):
            r.add("error", "node.id.coordinate",
                  f"{nid}: ID 에 좌표로 보이는 값이 있다 — 파서를 고치면 그래프가 끊긴다")
        if n.get("derivation") not in DERIVATIONS:
            r.add("error", "node.derivation",
                  f"{nid}: derivation '{n.get('derivation')}' 이 허용값 {DERIVATIONS} 밖이다")
        for prop in spec.required:
            if n.get(prop) in (None, ""):
                r.add("error", "node.required", f"{nid}: 필수 속성 '{prop}' 이 없다")
        if ntype == "Finding" and n.get("resolution") is not None:
            r.add("error", "finding.resolution",
                  f"{nid}: 룰이 resolution 을 채웠다 — 확정은 사람만 한다")

    evidenced = {e["source"] for e in edges if e.get("type") == "evidencedBy"}
    for n in nodes:
        spec = NODE_TYPES.get(n.get("type", ""))
        if spec and spec.requires_span and n.get("id") not in evidenced:
            r.add("error", "node.span",
                  f"{n.get('id')}: 근거(EvidenceSpan) 없는 {n.get('type')} 은 그래프에 있을 수 없다")

    for e in edges:
        etype = e.get("type", "")
        spec = EDGE_TYPES.get(etype)
        if spec is None:
            r.add("error", "edge.type", f"정의되지 않은 엣지 타입 '{etype}'")
            continue
        src, dst = by_id.get(e.get("source", "")), by_id.get(e.get("target", ""))
        if src is None:
            r.add("error", "edge.source", f"{etype}: 출발 노드를 찾을 수 없다 — {e.get('source')}")
        elif src.get("type") not in spec.domain:
            r.add("error", "edge.domain",
                  f"{etype}: 출발이 {src.get('type')} 인데 도메인은 {spec.domain} 이다")
        if dst is None:
            r.add("error", "edge.target", f"{etype}: 도착 노드를 찾을 수 없다 — {e.get('target')}")
        elif dst.get("type") not in spec.range:
            r.add("error", "edge.range",
                  f"{etype}: 도착이 {dst.get('type')} 인데 레인지는 {spec.range} 이다")

    return r


def schema_dict() -> dict[str, Any]:
    """스키마 자체를 기계가 읽을 수 있는 형태로 내보낸다."""
    return {
        "ontology": KB_ONTOLOGY_VERSION,
        "derivations": list(DERIVATIONS),
        "reviewable_derivations": list(REVIEWABLE_DERIVATIONS),
        "dimensions": dict(sorted(DIMENSION.items())),
        "nodes": {
            n.name: {
                "prefix": n.prefix, "ko": n.ko, "en": n.en,
                "id_parts": list(n.id_parts),
                "required": list(n.required), "optional": list(n.optional),
                "derivation": n.derivation, "requires_span": n.requires_span,
                "note": n.note,
            }
            for n in NODE_TYPES.values()
        },
        "edges": {
            e.name: {
                "ko": e.ko, "domain": list(e.domain), "range": list(e.range),
                "cardinality": e.cardinality, "derivation": e.derivation, "note": e.note,
            }
            for e in EDGE_TYPES.values()
        },
        "reserved_v0_2": RESERVED_V0_2,
    }


# --------------------------------------------------------------------------- #
# RDF 내보내기
# --------------------------------------------------------------------------- #
def to_turtle(graph: dict[str, Any], base: str = "http://gngmeta.com/ediag#") -> str:
    """Fuseki/SPARQL 적재용 TTL."""
    lines = [
        f"@prefix ed: <{base}> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]

    def esc(v: Any) -> str:
        if isinstance(v, bool):
            return f'"{str(v).lower()}"^^xsd:boolean'
        if isinstance(v, (int, float)):
            return f'"{v}"^^xsd:decimal'
        s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
        return f'"{s}"'

    def uri(node_id: str) -> str:
        return "ed:" + re.sub(r"[^\w.-]", "_", node_id)

    for n in graph["nodes"]:
        lines.append(f"{uri(n['id'])} rdf:type ed:{n['type']} ;")
        props = [f"    ed:{k} {esc(v)}" for k, v in n.items()
                 if k not in ("id", "type") and v is not None]
        lines.append(" ;\n".join(props) + " ." if props else '    rdfs:label "" .')
        lines.append("")

    for e in graph["edges"]:
        lines.append(f"{uri(e['source'])} ed:{e['type']} {uri(e['target'])} .")

    return "\n".join(lines)
