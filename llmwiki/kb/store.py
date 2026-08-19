"""지식베이스 저장소 — 업종 구획별 적재와 검색.

원 설계(RAG-AI_Gov)는 4채널 청크를 벡터 DB(xAI Collections → Qdrant)에 넣었다.
LLMWiki 에는 벡터 저장소가 없다. 문서 검색은 `llmwiki/server/search.py` 처럼
어휘 가중치 기반이고, 감사 추적은 `llmwiki/compliance/store.py` 처럼 append-only
파일이다. 그래서 같은 **규칙**을 이 두 관행 위에 다시 세운다.

바꾸지 않은 것이 넷 있다.

1. **게이트를 우회하지 않는다.** 적재는 `analyze()` 가 ``upload_allowed=True`` 를
   준 뒤에만 일어난다. 이 모듈에 "그냥 넣기" 인자는 없고, ``mask=False`` 로
   비식별을 꺼도 개인정보가 남아 있으면 적재가 중단된다.
2. **채널을 유지한다.** 표는 표 단위로 한 레코드에 넣는다. 행을 쪼개면 "어느 행
   어느 열의 값인가" 가 사라져 표를 파싱한 의미가 없어진다.
3. **업종이 구획을 가른다.** 원단위 분모가 업종마다 달라 섞으면 비교가 깨진다.
4. **적재 이력은 지워지지 않는다.** `ledger.jsonl` 은 덧붙이기뿐이다. 어떤 문서가
   언제 어떤 게이트 판정으로 들어왔는지가 남아야 감사에 답할 수 있다.

배치::

    <kb_dir>/
      ledger.jsonl                    적재 이력 (append-only)
      ediag__waste/<doc_hash>/
        analysis.json                 분석 결과 (게이트 판정 포함)
        graph.json                    온톨로지 그래프
        graph.ttl                     Fuseki 적재용
        channels.jsonl                **마스킹된** 채널 청크 = 검색 단위
        tables.xlsx                   엑셀 채널 (있으면)
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import gate, ontology, taxonomy

LEDGER = "ledger.jsonl"
ANALYSIS = "analysis.json"
GRAPH = "graph.json"
TURTLE = "graph.ttl"
CHANNELS = "channels.jsonl"
EXCEL = "tables.xlsx"

#: 글 채널을 묶을 때의 상한. 표·그림은 묶지 않는다.
MAX_TEXT_CHARS = 6000

#: 검색 가중치. 수치 질의는 표에서 답이 나오므로 표를 위로 둔다.
CHANNEL_WEIGHTS = {"table": 3, "text": 2, "image": 1}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def prepare(chunks: list[dict], *, mask: bool = True) -> tuple[list[dict], dict]:
    """적재 직전 비식별 처리와 **검산**.

    마스킹한 결과를 탐지기에 다시 넣어 잔존을 센다. 마스킹 규칙에 구멍이 있으면
    치환했다고 믿고 그대로 들어가는데, 그건 마스킹을 안 한 것보다 나쁘다. 잔존이
    있으면 빈 목록을 돌려주고 호출 측이 적재를 포기한다.
    """
    if not mask:
        residual = sum(len(gate.detect_pii(c["content"])) for c in chunks)
        return (chunks if not residual else []), {"masked": False, "residual_count": residual}

    cleaned: list[dict] = []
    masked_count = 0
    for c in chunks:
        text, n = gate.mask_text(c["content"])
        masked_count += n
        cleaned.append({**c, "content": text})
    residual = sum(len(gate.detect_pii(c["content"])) for c in cleaned)
    return (cleaned if not residual else []), {
        "masked": True, "masked_count": masked_count, "residual_count": residual,
    }


def channel_documents(chunks: Iterable[dict], *, max_chars: int = MAX_TEXT_CHARS) -> list[dict]:
    """채널별 청크를 검색 단위로 묶는다.

    글은 이어 붙이되 너무 길면 나눈다. 표와 그림은 **하나씩** 따로 둔다 — 표 두 개를
    한 레코드에 넣으면 검색이 엉뚱한 표를 근거로 답한다.
    """
    out: list[dict] = []
    buffer: list[dict] = []
    size = 0

    def flush() -> None:
        nonlocal buffer, size
        if not buffer:
            return
        out.append({
            "channel": buffer[0]["channel"],
            "page": buffer[0].get("page"),
            "anchor": buffer[0].get("anchor", ""),
            "content": "\n\n".join(
                f"### {c.get('anchor', '')} (p.{c.get('page', '?')})\n{c['content']}"
                for c in buffer
            ),
            "parts": len(buffer),
        })
        buffer, size = [], 0

    for chunk in chunks:
        if chunk["channel"] != "text":
            flush()
            out.append({
                "channel": chunk["channel"],
                "page": chunk.get("page"),
                "anchor": chunk.get("anchor", ""),
                "content": f"### {chunk.get('anchor', '')} (p.{chunk.get('page', '?')})\n"
                           f"{chunk['content']}",
                "parts": 1,
            })
            continue
        if size + len(chunk["content"]) > max_chars:
            flush()
        buffer.append(chunk)
        size += len(chunk["content"])
    flush()
    return out


class Store:
    """업종 구획으로 갈린 문서 지식베이스."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- 경로 ------------------------------------------------------------- #
    @property
    def ledger_path(self) -> Path:
        return self.root / LEDGER

    def dir_of(self, partition: str, doc_hash: str) -> Path:
        return self.root / _safe(partition) / _safe(doc_hash)

    # --- 적재 ------------------------------------------------------------- #
    def ingest(self, result: Any, chunks: list[dict] | None = None, *,
               mask: bool = True,
               destination: dict[str, Any] | None = None) -> dict[str, Any]:
        """분석 결과를 업종 구획에 적재한다.

        게이트가 막으면 아무것도 쓰지 않고 왜 막혔는지만 돌려준다. 반환값은 화면에
        그대로 쓸 수 있는 형태다.
        """
        if not getattr(result, "upload_allowed", False):
            return self._skip(result, "규제 게이트가 적재를 허용하지 않았다")
        if getattr(result, "needs_review", False):
            return self._skip(
                result, "업종 분류가 확정되지 않았다 — 업종을 지정해 다시 적재한다")

        chunks = list(chunks if chunks is not None else getattr(result, "chunks", []) or [])
        if not chunks:
            return self._skip(result, "적재할 채널 청크가 없다")

        cleaned, masking = prepare(chunks, mask=mask)
        if not cleaned:
            return self._skip(
                result,
                f"비식별 처리 후에도 개인정보 {masking['residual_count']}건이 남아 중단했다",
                masking=masking,
            )

        documents = channel_documents(cleaned)
        target = self.dir_of(result.partition, result.doc_hash)
        target.mkdir(parents=True, exist_ok=True)

        _write_jsonl(target / CHANNELS, [
            {**d, "doc_hash": result.doc_hash, "sector": result.sector,
             "sector_name": result.sector_name, "masked": masking.get("masked", True),
             "source": result.filename, "index": i, "total": len(documents),
             "unit_basis": taxonomy.get(result.sector).unit_basis,
             "ontology": ontology.KB_ONTOLOGY_VERSION}
            for i, d in enumerate(documents)
        ])
        _write_json(target / ANALYSIS, result.to_dict())
        if result.graph is not None:
            _write_json(target / GRAPH, result.graph)
            (target / TURTLE).write_text(ontology.to_turtle(result.graph), encoding="utf-8")
        if result.excel_path and Path(result.excel_path).exists():
            shutil.copyfile(result.excel_path, target / EXCEL)

        by_channel: dict[str, int] = {}
        for d in documents:
            by_channel[d["channel"]] = by_channel.get(d["channel"], 0) + 1

        record = {
            "doc_hash": result.doc_hash,
            "filename": result.filename,
            "sector": result.sector,
            "sector_name": result.sector_name,
            "partition": result.partition,
            "stored": len(documents),
            "by_channel": dict(sorted(by_channel.items())),
            "masked": masking.get("masked", True),
            "masked_count": masking.get("masked_count", 0),
            "pii_detected": result.gate.get("pii_detected", 0),
            "verdict": result.gate.get("verdict", ""),
            # 어느 공급자를 기준으로 국외 이전 해당성을 판단했는지. 같은 문서라도
            # 목적지가 바뀌면 판정이 달라지므로, 판정만 남기면 재현되지 않는다.
            "destination": destination or result.gate.get("destination", {}),
            "graph_nodes": (result.graph_stats or {}).get("nodes", 0),
            "ontology": ontology.KB_ONTOLOGY_VERSION,
            "path": str(target),
            "ingested_at": now_iso(),
        }
        _append_jsonl(self.ledger_path, [record])
        return record

    def _skip(self, result: Any, why: str, **extra: Any) -> dict[str, Any]:
        return {
            "doc_hash": getattr(result, "doc_hash", ""),
            "filename": getattr(result, "filename", ""),
            "sector": getattr(result, "sector", ""),
            "partition": getattr(result, "partition", None),
            "stored": 0,
            "skipped": why,
            **extra,
        }

    # --- 조회 ------------------------------------------------------------- #
    def ledger(self) -> list[dict[str, Any]]:
        return _read_jsonl(self.ledger_path)

    def documents(self, sector: str | None = None) -> list[dict[str, Any]]:
        """적재된 문서 목록. 같은 문서를 다시 적재하면 최신 레코드가 현재 상태다."""
        latest: dict[str, dict[str, Any]] = {}
        for rec in self.ledger():
            latest[rec["doc_hash"]] = rec
        rows = [r for r in latest.values() if not sector or r.get("sector") == sector]
        rows.sort(key=lambda r: r.get("ingested_at", ""), reverse=True)
        return rows

    def record(self, doc_hash: str) -> dict[str, Any] | None:
        return next((r for r in self.documents() if r["doc_hash"] == doc_hash), None)

    def _file(self, doc_hash: str, name: str) -> Path | None:
        rec = self.record(doc_hash)
        if not rec:
            return None
        path = self.dir_of(rec["partition"], doc_hash) / name
        return path if path.exists() else None

    def analysis(self, doc_hash: str) -> dict[str, Any] | None:
        path = self._file(doc_hash, ANALYSIS)
        return json.loads(path.read_text(encoding="utf-8")) if path else None

    def graph(self, doc_hash: str) -> dict[str, Any] | None:
        path = self._file(doc_hash, GRAPH)
        return json.loads(path.read_text(encoding="utf-8")) if path else None

    def turtle(self, doc_hash: str) -> str | None:
        path = self._file(doc_hash, TURTLE)
        return path.read_text(encoding="utf-8") if path else None

    def excel(self, doc_hash: str) -> Path | None:
        return self._file(doc_hash, EXCEL)

    def channels(self, doc_hash: str) -> list[dict[str, Any]]:
        path = self._file(doc_hash, CHANNELS)
        return _read_jsonl(path) if path else []

    def stats(self) -> dict[str, Any]:
        docs = self.documents()
        by_sector: dict[str, int] = {}
        by_channel: dict[str, int] = {}
        for d in docs:
            by_sector[d["sector"]] = by_sector.get(d["sector"], 0) + 1
            for ch, n in (d.get("by_channel") or {}).items():
                by_channel[ch] = by_channel.get(ch, 0) + n
        return {
            "documents": len(docs),
            "records": sum(d.get("stored", 0) for d in docs),
            "sectors": dict(sorted(by_sector.items())),
            "channels": dict(sorted(by_channel.items())),
            "masked_all": all(d.get("masked", True) for d in docs),
        }

    # --- 검색 ------------------------------------------------------------- #
    def search(self, query: str, *, sector: str | None = None, channel: str | None = None,
               limit: int = 20) -> list[dict[str, Any]]:
        """어휘 검색. 업종과 채널로 **실제로** 필터를 건다.

        필터를 자연어 지시로만 넘기면 무시될 수 있다 — 업종별 구획 분리 구조에서는
        그게 치명적이다. 그래서 필터는 후보 집합을 줄이는 코드로 둔다.
        """
        terms = [t for t in re.split(r"\s+", query.strip().lower()) if t]
        if not terms:
            return []

        hits: list[dict[str, Any]] = []
        for doc in self.documents(sector):
            for rec in self.channels(doc["doc_hash"]):
                if channel and rec.get("channel") != channel:
                    continue
                body = rec.get("content", "")
                low = body.lower()
                score = 0
                if not all(t in low for t in terms):
                    continue
                weight = CHANNEL_WEIGHTS.get(rec.get("channel", ""), 1)
                for t in terms:
                    score += min(low.count(t), 10) * weight
                hits.append({
                    "doc_hash": doc["doc_hash"],
                    "filename": doc.get("filename", ""),
                    "sector": doc.get("sector", ""),
                    "sector_name": doc.get("sector_name", ""),
                    "channel": rec.get("channel", ""),
                    "anchor": rec.get("anchor", ""),
                    "page": rec.get("page"),
                    "score": score,
                    "snippet": _snippet(body, terms),
                })
        hits.sort(key=lambda h: (-h["score"], h["doc_hash"], h["anchor"]))
        return hits[:limit]


# --------------------------------------------------------------------------- #
def _snippet(body: str, terms: list[str], width: int = 120) -> str:
    low = body.lower()
    for term in terms:
        i = low.find(term)
        if i >= 0:
            start = max(0, i - width // 3)
            end = min(len(body), i + width)
            text = body[start:end].replace("\n", " ").strip()
            return ("… " if start else "") + text + (" …" if end < len(body) else "")
    return body[:width].replace("\n", " ").strip()


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in str(name))


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


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
