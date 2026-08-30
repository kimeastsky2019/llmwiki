"""지식그래프 저장소 (L2) — 승인본과 제안본을 물리적으로 가른다.

핵심은 세 줄이다.

1. **저널은 append-only 다.** 삭제 연산이 아예 없다. 폐기는 `obsolete` 레코드를
   덧붙이는 것이고, 원래 레코드는 그대로 남는다. 과거 판정의 근거가 사라지지
   않으므로 감사 추적이 끊기지 않는다.
2. **판정 엔진은 승인본만 본다.** 제안은 별도 파일(`changesets.jsonl`)에 쌓이고,
   승인되기 전에는 `approved()` 결과에 절대 나타나지 않는다. 위키백과의
   Flagged Revisions 와 같은 구조 — 제안이 아무리 쌓여도 판정은 흔들리지 않는다.
3. **`as_of` 로 과거를 되돌린다.** 각 레코드에 시스템 시각(`recorded_at`)이 박혀
   있어, 1년 전 시점의 그래프를 그대로 재구성할 수 있다. 여기에 노드가 들고 있는
   업무 시각(`valid_from`/`valid_to`)이 겹쳐 양시간 모델이 된다.

파일 배치::

    <compliance_dir>/
      journal.jsonl      승인된 리비전 (append-only)
      changesets.jsonl   변경 제안과 그 상태 변화 (append-only, 최신 레코드가 유효)
      documents/         원문 (스팬 대조용)
      metrics.json       지표 측정값
      goldset.json       골드셋
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .ontology import EDGE_TYPES, NODE_TYPES, edge_key, node_id

JOURNAL = "journal.jsonl"
CHANGESETS = "changesets.jsonl"
DOCUMENTS = "documents"


# --------------------------------------------------------------------------- #
# 시각
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def today_iso() -> str:
    return date.today().isoformat()


def parse_date(value: Any) -> date | None:
    """YYYY-MM-DD 또는 ISO 타임스탬프를 날짜로. 못 읽으면 None."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def days_between(a: date, b: date) -> int:
    return (b - a).days


# --------------------------------------------------------------------------- #
# 그래프 (읽기 전용 뷰)
# --------------------------------------------------------------------------- #
class Graph:
    """저널을 재생해서 만든 한 시점의 그래프. 판정·분석의 입력이다."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.version: str = ""
        #: 이 그래프를 만든 마지막 저널 레코드 번호. 재현의 좌표다.
        self.seq: int = 0

    # --- 쓰기 (재생 전용) --- #
    def put_node(
        self, node_type: str, props: dict[str, Any], *,
        derivation: str | None = None, spans: list[dict[str, Any]] | None = None,
        recorded_at: str = "", changeset: str = "",
    ) -> str:
        nid = node_id(node_type, **props)
        current = self.nodes.get(nid, {})
        merged = {**current.get("props", {}), **props}
        self.nodes[nid] = {
            "id": nid,
            "type": node_type,
            "derivation": derivation or NODE_TYPES[node_type].derivation,
            "props": merged,
            "spans": spans if spans is not None else current.get("spans", []),
            "status": merged.get("status", current.get("status", "active")),
            "recorded_at": recorded_at or current.get("recorded_at", ""),
            "changeset": changeset or current.get("changeset", ""),
        }
        return nid

    def put_edge(
        self, edge_type: str, source: str, target: str,
        props: dict[str, Any] | None = None, *,
        derivation: str | None = None, spans: list[dict[str, Any]] | None = None,
        recorded_at: str = "", changeset: str = "",
    ) -> str:
        props = dict(props or {})
        key = edge_key(edge_type, source, target, props)
        current = self.edges.get(key, {})
        self.edges[key] = {
            "key": key,
            "type": edge_type,
            "source": source,
            "target": target,
            "derivation": derivation or EDGE_TYPES[edge_type].derivation,
            "props": {**current.get("props", {}), **props},
            "spans": spans if spans is not None else current.get("spans", []),
            "status": props.get("status", current.get("status", "active")),
            "recorded_at": recorded_at or current.get("recorded_at", ""),
            "changeset": changeset or current.get("changeset", ""),
        }
        return key

    def obsolete_node(self, nid: str, replaced_by: str = "", *, recorded_at: str = "") -> None:
        """삭제가 아니라 폐기. 노드는 남고 상태만 내려간다."""
        node = self.nodes.get(nid)
        if node is None:
            return
        node["status"] = "obsolete"
        node["props"]["status"] = "obsolete"
        if replaced_by:
            node["props"]["replaced_by"] = replaced_by
        node["obsoleted_at"] = recorded_at

    def obsolete_edge(self, key: str, *, recorded_at: str = "") -> None:
        edge = self.edges.get(key)
        if edge is None:
            return
        edge["status"] = "obsolete"
        edge["obsoleted_at"] = recorded_at

    # --- 읽기 --- #
    def node(self, nid: str) -> dict[str, Any] | None:
        return self.nodes.get(nid)

    def props(self, nid: str) -> dict[str, Any]:
        node = self.nodes.get(nid)
        return node["props"] if node else {}

    def of_type(self, node_type: str, *, active_only: bool = True) -> list[dict[str, Any]]:
        return [
            n for n in self.nodes.values()
            if n["type"] == node_type and (not active_only or n["status"] == "active")
        ]

    def out_edges(
        self, source: str, edge_type: str | None = None, *, active_only: bool = True
    ) -> list[dict[str, Any]]:
        return [
            e for e in self.edges.values()
            if e["source"] == source
            and (edge_type is None or e["type"] == edge_type)
            and (not active_only or e["status"] == "active")
        ]

    def in_edges(
        self, target: str, edge_type: str | None = None, *, active_only: bool = True
    ) -> list[dict[str, Any]]:
        return [
            e for e in self.edges.values()
            if e["target"] == target
            and (edge_type is None or e["type"] == edge_type)
            and (not active_only or e["status"] == "active")
        ]

    def targets(self, source: str, edge_type: str) -> list[str]:
        return [e["target"] for e in self.out_edges(source, edge_type)]

    def sources(self, target: str, edge_type: str) -> list[str]:
        return [e["source"] for e in self.in_edges(target, edge_type)]

    def active_nodes(self) -> list[dict[str, Any]]:
        return [n for n in self.nodes.values() if n["status"] == "active"]

    def active_edges(self) -> list[dict[str, Any]]:
        return [e for e in self.edges.values() if e["status"] == "active"]

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in self.active_nodes():
            out[n["type"]] = out.get(n["type"], 0) + 1
        return dict(sorted(out.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
        }

    def copy(self) -> "Graph":
        clone = Graph()
        clone.version = self.version
        clone.seq = self.seq
        clone.nodes = {k: json.loads(json.dumps(v, ensure_ascii=False))
                       for k, v in self.nodes.items()}
        clone.edges = {k: json.loads(json.dumps(v, ensure_ascii=False))
                       for k, v in self.edges.items()}
        return clone


# --------------------------------------------------------------------------- #
# 저장소
# --------------------------------------------------------------------------- #
class Store:
    """append-only 저널 위에 세워진 그래프 저장소."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / DOCUMENTS).mkdir(exist_ok=True)

    # --- 경로 --- #
    @property
    def journal_path(self) -> Path:
        return self.root / JOURNAL

    @property
    def changesets_path(self) -> Path:
        return self.root / CHANGESETS

    @property
    def documents_dir(self) -> Path:
        return self.root / DOCUMENTS

    # --- 저널 --- #
    def read_journal(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.journal_path)

    def next_seq(self) -> int:
        records = self.read_journal()
        return (records[-1]["seq"] + 1) if records else 1

    def append(self, records: Iterable[dict[str, Any]]) -> int:
        """저널에 덧붙인다. 여기에 '수정' 도 '삭제' 도 없다 — 덧붙이기뿐이다."""
        records = list(records)
        if not records:
            return 0
        seq = self.next_seq()
        stamped = []
        for rec in records:
            rec = dict(rec)
            rec["seq"] = seq
            rec.setdefault("recorded_at", now_iso())
            stamped.append(rec)
            seq += 1
        _append_jsonl(self.journal_path, stamped)
        return len(stamped)

    # --- 승인본 --- #
    def approved(self, *, as_of: str | None = None, upto_seq: int | None = None) -> Graph:
        """승인 그래프. as_of 나 upto_seq 를 주면 그 시점으로 되돌린다.

        판정 엔진이 보는 유일한 뷰다. 제안본은 여기 섞이지 않는다.

        `as_of` 는 사람이 쓰는 시각 기준이고, `upto_seq` 는 레코드 일련번호 기준이다.
        같은 초에 여러 건이 병합되면 시각만으로는 경계가 흐려지므로, 정확한 재현이
        필요할 때는 seq 를 쓴다 (판정 결과에 남길 값도 seq 다).
        """
        graph = Graph()
        last = ""
        last_seq = 0
        for rec in self.read_journal():
            if as_of and rec.get("recorded_at", "") > as_of:
                continue
            if upto_seq is not None and int(rec.get("seq", 0)) > upto_seq:
                continue
            _apply(graph, rec)
            last = rec.get("recorded_at", last)
            last_seq = int(rec.get("seq", last_seq))
        graph.version = as_of or last
        graph.seq = last_seq
        return graph

    def replay(self, records: Iterable[dict[str, Any]], base: Graph | None = None) -> Graph:
        """저널에 쓰지 않고 레코드를 적용한 가상 그래프 — 제안본 미리보기용."""
        graph = base.copy() if base is not None else Graph()
        for rec in records:
            _apply(graph, rec)
        return graph

    # --- 제안본 --- #
    def read_changesets(self) -> dict[str, dict[str, Any]]:
        """ID 별 최신 상태. 이력은 남고 최신 레코드가 현재 상태다."""
        latest: dict[str, dict[str, Any]] = {}
        for rec in _read_jsonl(self.changesets_path):
            cid = rec.get("changeset_id")
            if cid:
                latest[cid] = rec
        return latest

    def changeset_history(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.changesets_path)

    def put_changeset(self, record: dict[str, Any]) -> None:
        record = dict(record)
        record.setdefault("recorded_at", now_iso())
        _append_jsonl(self.changesets_path, [record])

    def changeset(self, changeset_id: str) -> dict[str, Any] | None:
        return self.read_changesets().get(changeset_id)

    def pending(self) -> list[dict[str, Any]]:
        return [
            cs for cs in self.read_changesets().values()
            if cs.get("status") == "pending_review"
        ]

    # --- 원문 --- #
    def put_document(self, doc_id: str, text: str) -> Path:
        path = self.documents_dir / f"{_safe(doc_id)}.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def document(self, doc_id: str) -> str | None:
        path = self.documents_dir / f"{_safe(doc_id)}.txt"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def documents(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for path in sorted(self.documents_dir.glob("*.txt")):
            out[path.stem] = path.read_text(encoding="utf-8")
        return out

    # --- 부속 파일 --- #
    def read_json(self, name: str, default: Any = None) -> Any:
        path = self.root / name
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def write_json(self, name: str, payload: Any) -> Path:
        path = self.root / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    @property
    def metrics(self) -> dict[str, dict[str, float]]:
        """서비스별 지표 측정값: {service_uuid: {metric: value}}."""
        return self.read_json("metrics.json", {}) or {}

    @property
    def goldset(self) -> list[dict[str, Any]]:
        return self.read_json("goldset.json", []) or []


# --------------------------------------------------------------------------- #
# 저널 레코드
# --------------------------------------------------------------------------- #
def node_record(
    node_type: str, props: dict[str, Any], *,
    derivation: str | None = None, spans: list[dict[str, Any]] | None = None,
    changeset: str = "",
) -> dict[str, Any]:
    return {
        "kind": "node", "op": "upsert", "node_type": node_type,
        "id": node_id(node_type, **props), "props": props,
        "derivation": derivation, "spans": spans or [], "changeset": changeset,
    }


def edge_record(
    edge_type: str, source: str, target: str, props: dict[str, Any] | None = None, *,
    derivation: str | None = None, spans: list[dict[str, Any]] | None = None,
    changeset: str = "",
) -> dict[str, Any]:
    props = dict(props or {})
    return {
        "kind": "edge", "op": "upsert", "edge_type": edge_type,
        "key": edge_key(edge_type, source, target, props),
        "source": source, "target": target, "props": props,
        "derivation": derivation, "spans": spans or [], "changeset": changeset,
    }


def obsolete_record(nid: str, replaced_by: str = "", *, changeset: str = "") -> dict[str, Any]:
    return {
        "kind": "node", "op": "obsolete", "id": nid,
        "replaced_by": replaced_by, "changeset": changeset,
    }


def obsolete_edge_record(key: str, *, changeset: str = "") -> dict[str, Any]:
    return {"kind": "edge", "op": "obsolete", "key": key, "changeset": changeset}


def _apply(graph: Graph, rec: dict[str, Any]) -> None:
    kind, op = rec.get("kind"), rec.get("op")
    stamp = rec.get("recorded_at", "")
    cs = rec.get("changeset", "")
    if kind == "node" and op == "upsert":
        graph.put_node(
            rec["node_type"], rec["props"], derivation=rec.get("derivation"),
            spans=rec.get("spans"), recorded_at=stamp, changeset=cs,
        )
    elif kind == "node" and op == "obsolete":
        graph.obsolete_node(rec["id"], rec.get("replaced_by", ""), recorded_at=stamp)
    elif kind == "edge" and op == "upsert":
        graph.put_edge(
            rec["edge_type"], rec["source"], rec["target"], rec.get("props"),
            derivation=rec.get("derivation"), spans=rec.get("spans"),
            recorded_at=stamp, changeset=cs,
        )
    elif kind == "edge" and op == "obsolete":
        graph.obsolete_edge(rec["key"], recorded_at=stamp)


# --------------------------------------------------------------------------- #
def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _append_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)


def iter_journal(path: str | Path) -> Iterator[dict[str, Any]]:
    yield from _read_jsonl(Path(path))
