"""위키 저장소 — 파일이 곧 진실이다 (P1).

Single Source of Truth 는 위키다. 인덱스도 그래프도 검색 결과도 **여기서 재생성**하고,
반대 방향으로는 절대 쓰지 않는다. 산출물을 직접 고치기 시작하면 소스와 산출물이
갈라지고, 그 순간 파이프라인 전체를 다시 만들어야 한다.

배치::

    <wiki_dir>/
      index.md          카탈로그 — log 와 페이지에서 매번 재생성한다
      log.md            변경 이력 (사람이 읽는 형태, log.jsonl 에서 재생성)
      log.jsonl         변경 이력 원본 (append-only)
      review.jsonl      검증 저널 (append-only, review.py 가 쓴다)
      sources/  entities/  measures/  metrics/  concepts/  regulations/

`log.jsonl` 은 덧붙이기뿐이다. 페이지를 지우는 연산도 두지 않았다 — 폐기는
`status: deprecated` 로 남기는 것이지 파일을 없애는 것이 아니다. 없앤 페이지를
누군가 인용하고 있었다면 그 인용은 영영 추적 불가가 된다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import contract, page as page_mod
from .page import WikiPage

INDEX = "index.md"
LOG_MD = "log.md"
LOG_JSONL = "log.jsonl"

#: 변경 이력의 닫힌 집합. 새 동작이 필요하면 먼저 여기에 넣는다.
ACTIONS: tuple[str, ...] = ("created", "updated", "unchanged", "status", "reviewed", "rejected")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class WikiStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        for d in contract.DIRECTORIES:
            (self.root / d).mkdir(parents=True, exist_ok=True)

    # --- 경로 ------------------------------------------------------------- #
    @property
    def index_path(self) -> Path:
        return self.root / INDEX

    @property
    def log_path(self) -> Path:
        return self.root / LOG_JSONL

    def path_of(self, p: WikiPage) -> Path:
        return self.root / p.relative_path()

    # --- 읽기 ------------------------------------------------------------- #
    def _files(self) -> list[Path]:
        out: list[Path] = []
        for d in contract.DIRECTORIES:
            out.extend(sorted((self.root / d).glob("*.md")))
        return out

    def pages(self, *, page_type: str | None = None, status: str | None = None,
              acl_max: str | None = None) -> list[WikiPage]:
        """페이지 전부(또는 필터). 필터는 코드가 건다 — 화면 문구로 거는 필터는 새어 나간다."""
        out: list[WikiPage] = []
        for f in self._files():
            try:
                p = page_mod.loads(f.read_text(encoding="utf-8"),
                                   path=str(f.relative_to(self.root)))
            except page_mod.PageError as exc:
                # 깨진 파일은 조용히 넘기지 않는다. lint 가 볼 수 있도록 자리를 남긴다.
                out.append(WikiPage(front_matter={}, body="",
                                    path=str(f.relative_to(self.root)), errors=[str(exc)]))
                continue
            if page_type and p.type != page_type:
                continue
            if status and p.status != status:
                continue
            if acl_max and contract.acl_rank(p.acl) > contract.acl_rank(acl_max):
                continue
            out.append(p)
        out.sort(key=lambda p: (p.type, p.stable_id))
        return out

    def read(self, stable_id: str) -> WikiPage | None:
        for f in self._files():
            if f.stem == stable_id:
                return page_mod.loads(f.read_text(encoding="utf-8"),
                                      path=str(f.relative_to(self.root)))
        return None

    def exists(self, stable_id: str) -> bool:
        return any(f.stem == stable_id for f in self._files())

    def ids(self) -> set[str]:
        return {f.stem for f in self._files()}

    def backlinks(self, stable_id: str, pages: list[WikiPage] | None = None) -> list[str]:
        pages = pages if pages is not None else self.pages()
        return sorted(p.stable_id for p in pages
                      if p.stable_id != stable_id and stable_id in p.related)

    # --- 쓰기 ------------------------------------------------------------- #
    def write(self, p: WikiPage, *, actor: str = "pipeline", note: str = "") -> dict[str, Any]:
        """페이지를 저장한다. 내용이 같으면 버전을 올리지 않는다.

        같은 문서를 다시 적재할 때마다 버전이 올라가면 이력이 의미를 잃는다.
        **본문이 실제로 바뀐 경우에만** 버전이 오른다.
        """
        if p.type not in contract.PAGE_TYPES:
            raise KeyError(f"정의되지 않은 페이지 타입이다: {p.type}")
        p.body = p.body.strip()
        p.refresh_hash()

        existing = self.read(p.stable_id)
        action = "created"
        if existing is not None:
            if existing.front_matter.get("content_hash") == p.front_matter["content_hash"]:
                action = "unchanged"
                # 이미 검토된 페이지를 파이프라인이 draft 로 되돌리지 않는다.
                p.front_matter["status"] = existing.status
                p.front_matter["version"] = existing.version
            else:
                action = "updated"
                p.front_matter["version"] = existing.version + 1
                # 내용이 바뀌면 검토는 무효다. 다시 검토받아야 한다.
                if existing.status == "reviewed":
                    p.front_matter["status"] = "draft"

        target = self.path_of(p)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = p.dumps()
        if action != "unchanged" or not target.exists():
            target.write_text(text, encoding="utf-8")
        p.path = str(target.relative_to(self.root))

        record = {
            "at": now_iso(),
            "action": action,
            "stable_id": p.stable_id,
            "type": p.type,
            "version": p.version,
            "status": p.status,
            "acl": p.acl,
            "actor": actor,
            "note": note,
            "content_hash": p.front_matter.get("content_hash", ""),
        }
        if action != "unchanged":
            self.append_log(record)
        return record

    def set_status(self, stable_id: str, status: str, *, actor: str,
                   note: str = "") -> dict[str, Any]:
        """상태만 바꾼다. 본문을 건드리지 않으므로 버전은 오르지 않는다."""
        if status not in contract.STATUSES:
            raise KeyError(f"정의되지 않은 상태다: {status}")
        p = self.read(stable_id)
        if p is None:
            raise KeyError(f"페이지가 없다: {stable_id}")
        before = p.status
        p.front_matter["status"] = status
        self.path_of(p).write_text(p.dumps(), encoding="utf-8")
        record = {
            "at": now_iso(), "action": "status", "stable_id": stable_id, "type": p.type,
            "version": p.version, "status": status, "from": before, "acl": p.acl,
            "actor": actor, "note": note,
        }
        self.append_log(record)
        return record

    # --- 이력 ------------------------------------------------------------- #
    def append_log(self, record: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._render_log()

    def log(self, limit: int = 200) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        rows = [json.loads(l) for l in self.log_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return rows[-limit:][::-1]

    def _render_log(self) -> None:
        """`log.md` 는 사람이 읽는 사본이다. 원본은 언제나 `log.jsonl`."""
        rows = self.log(limit=1000)
        lines = [
            "# 변경 이력",
            "",
            "> `log.jsonl` 에서 재생성된다. 이 파일을 직접 고쳐도 원본은 바뀌지 않는다.",
            "",
            "| 시각 | 동작 | 페이지 | v | 상태 | 작업자 | 비고 |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            lines.append(
                f"| {r.get('at','')} | {r.get('action','')} | "
                f"[[{r.get('stable_id','')}]] | {r.get('version','')} | "
                f"{r.get('status','')} | {r.get('actor','')} | {r.get('note','')} |"
            )
        (self.root / LOG_MD).write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- 카탈로그 --------------------------------------------------------- #
    def rebuild_index(self) -> Path:
        """`index.md` 재생성. 사람이 읽는 카탈로그이자 LLM 의 진입점이다.

        페이지가 100건을 넘기면 이 텍스트 카탈로그만으로는 검색이 버티지 못한다.
        그래서 검색은 `retrieval.py` 의 하이브리드 인덱스가 따로 맡고, 여기는
        **구조를 보여주는 목차**로 남는다.
        """
        pages = self.pages()
        by_type: dict[str, list[WikiPage]] = {}
        for p in pages:
            by_type.setdefault(p.type, []).append(p)

        lines = [
            "# 에너지 진단 위키 — 카탈로그",
            "",
            "> 이 파일은 `llmwiki wiki index` 가 재생성한다. 직접 고치지 않는다 (P1).",
            "",
            f"- 페이지 {len(pages)}건",
            f"- 검토 완료 {sum(1 for p in pages if p.status == 'reviewed')}건 / "
            f"초안 {sum(1 for p in pages if p.status == 'draft')}건",
            f"- 수치 검산 통과 {sum(1 for p in pages if p.numeric_verified)}건",
            "",
        ]
        for name, meta in contract.PAGE_TYPES.items():
            group = by_type.get(name, [])
            if not group:
                continue
            lines.append(f"## {meta.ko} ({name}) — {len(group)}건")
            lines.append("")
            for p in group:
                flags = []
                if p.status != "reviewed":
                    flags.append(p.status)
                if not p.numeric_verified:
                    flags.append("미검산")
                if p.acl in contract.ACL_INTERNAL_ONLY:
                    flags.append(p.acl)
                suffix = f" — {', '.join(flags)}" if flags else ""
                lines.append(f"- [[{p.stable_id}]] {p.title}{suffix}")
            lines.append("")
        self.index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return self.index_path

    # --- 집계 ------------------------------------------------------------- #
    def stats(self) -> dict[str, Any]:
        pages = self.pages()
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_acl: dict[str, int] = {}
        for p in pages:
            by_type[p.type] = by_type.get(p.type, 0) + 1
            by_status[p.status] = by_status.get(p.status, 0) + 1
            by_acl[p.acl] = by_acl.get(p.acl, 0) + 1
        return {
            "pages": len(pages),
            "by_type": dict(sorted(by_type.items())),
            "by_status": dict(sorted(by_status.items())),
            "by_acl": dict(sorted(by_acl.items())),
            "numeric_verified": sum(1 for p in pages if p.numeric_verified),
            "broken_pages": sum(1 for p in pages if p.errors),
        }

    def graph(self, pages: list[WikiPage] | None = None) -> dict[str, Any]:
        """페이지·링크 그래프. 화면의 그래프 뷰와 고아 판정이 같은 자료를 본다."""
        pages = pages if pages is not None else self.pages()
        ids = {p.stable_id for p in pages}
        nodes = [
            {"id": p.stable_id, "type": p.type, "title": p.title, "status": p.status,
             "acl": p.acl, "numeric_verified": p.numeric_verified}
            for p in pages
        ]
        edges = [
            {"source": p.stable_id, "target": t, "resolved": t in ids}
            for p in pages for t in p.related
        ]
        return {"nodes": nodes, "edges": edges,
                "stats": {"nodes": len(nodes), "edges": len(edges),
                          "unresolved": sum(1 for e in edges if not e["resolved"])}}


def write_all(store: WikiStore, pages: Iterable[WikiPage], *, actor: str = "pipeline",
              note: str = "") -> list[dict[str, Any]]:
    records = [store.write(p, actor=actor, note=note) for p in pages]
    store.rebuild_index()
    return records
