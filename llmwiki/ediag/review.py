"""검증 워크플로 — 판정은 룰이, 확정은 사람이.

`llmwiki/compliance/` 의 커밋 결재와 같은 구조다. 파이프라인이 만든 것은 전부
`draft` 로 태어나고, 사람이 서명해야 `reviewed` 가 된다. 서명 기록은 `review.jsonl`
에 덧붙기만 한다 — 지우는 연산이 없다.

세 가지를 강제한다.

1. **차단 위반이 있으면 승인할 수 없다.** ACL 상속 위반이나 stable_id 중복은
   사람이 "확인했다" 고 넘길 수 있는 종류가 아니다. 고쳐야 통과한다.
2. **검산 실패는 명시적으로 인지해야 승인된다.** `acknowledge_unverified=True` 를
   주지 않으면 거부한다. 실수로 눌러서 미검산 값이 확정되는 경로를 막는다.
   (인공지능 기본법 제34조의 인적 감독은 '눌렀다' 가 아니라 '보고 판단했다' 여야 한다.)
3. **본문이 바뀌면 검토가 무효다.** 저장소가 `updated` 시 상태를 `draft` 로 되돌린다
   (`store.WikiStore.write`). 검토한 내용과 다른 것이 검토됨으로 남지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import lint as lint_mod
from .store import WikiStore

REVIEW_JOURNAL = "review.jsonl"

#: 검토 결정의 닫힌 집합.
DECISIONS: tuple[str, ...] = ("approve", "reject", "deprecate")

#: 승인을 막는 lint 코드. 사람이 넘길 수 있는 종류가 아니다.
BLOCKING_CODES: frozenset[str] = frozenset({"acl.inheritance", "id.duplicate"})


class ReviewError(RuntimeError):
    """승인 조건을 만족하지 못했다. 조용히 통과시키지 않는다."""


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class QueueItem:
    stable_id: str
    type: str
    title: str
    status: str
    acl: str
    numeric_verified: bool
    priority: int
    reasons: list[str] = field(default_factory=list)
    blocking: list[str] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def journal_path(store: WikiStore) -> Path:
    return store.root / REVIEW_JOURNAL


def journal(store: WikiStore, *, stable_id: str | None = None,
            limit: int = 200) -> list[dict[str, Any]]:
    path = journal_path(store)
    if not path.exists():
        return []
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if stable_id:
        rows = [r for r in rows if r.get("stable_id") == stable_id]
    return rows[-limit:][::-1]


def _append(store: WikiStore, record: dict[str, Any]) -> None:
    path = journal_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# 큐
# --------------------------------------------------------------------------- #
def queue(store: WikiStore, *, result: lint_mod.LintResult | None = None,
          limit: int = 200) -> list[QueueItem]:
    """검토가 필요한 페이지를 우선순위 순으로.

    우선순위는 '검토하지 않으면 무엇이 잘못되는가' 로 매긴다. 배포를 막는 것 →
    값이 틀릴 수 있는 것 → 아직 아무도 안 본 것 순이다.
    """
    pages = store.pages()
    res = result or lint_mod.run(store, pages=pages)
    by_page: dict[str, list[lint_mod.Finding]] = {}
    for f in res.findings:
        by_page.setdefault(f.page, []).append(f)

    items: list[QueueItem] = []
    for p in pages:
        if not p.stable_id or p.status == "deprecated":
            continue
        findings = by_page.get(p.stable_id, [])
        blocking = [f.code for f in findings if f.code in BLOCKING_CODES]
        serious = blocking or [f for f in findings if f.severity in ("blocker", "error")]
        if p.status == "reviewed" and not serious:
            # 이미 서명이 끝난 페이지다. 미검산이라도 검토자가 인지하고 확정했으므로
            # 큐에 계속 남기지 않는다 — 남기면 큐가 '치울 수 없는 목록'이 되고,
            # 그러면 아무도 큐를 보지 않는다. 본문이 바뀌면 저장소가 draft 로
            # 되돌리므로 그때 다시 올라온다.
            continue
        reasons: list[str] = []
        priority = 0
        if blocking:
            reasons.append("배포 차단 위반이 있다")
            priority = 100
        if not p.numeric_verified:
            reasons.append("수치 검산 미통과")
            priority = max(priority, 60)
        if any(f.severity == "error" for f in findings):
            reasons.append("컨트랙트·링크 오류")
            priority = max(priority, 50)
        if p.status == "draft":
            reasons.append("초안 상태")
            priority = max(priority, 20)
        if "[검토 필요]" in p.body:
            reasons.append("본문에 검토 필요 표시")
            priority = max(priority, 10)
        if not reasons:
            continue
        items.append(QueueItem(
            stable_id=p.stable_id, type=p.type, title=p.title, status=p.status,
            acl=p.acl, numeric_verified=p.numeric_verified, priority=priority,
            reasons=reasons, blocking=blocking,
            findings=[f.to_dict() for f in findings]))
    items.sort(key=lambda i: (-i.priority, i.stable_id))
    return items[:limit]


# --------------------------------------------------------------------------- #
# 결정
# --------------------------------------------------------------------------- #
def decide(store: WikiStore, stable_id: str, decision: str, *, actor: str,
           note: str = "", acknowledge_unverified: bool = False,
           result: lint_mod.LintResult | None = None) -> dict[str, Any]:
    """검토 결정을 기록하고 상태를 옮긴다."""
    if decision not in DECISIONS:
        raise ReviewError(f"정의되지 않은 결정이다: {decision} (허용: {', '.join(DECISIONS)})")
    if not actor.strip():
        raise ReviewError("서명 없이 확정할 수 없다 — 검토자를 지정한다")

    page = store.read(stable_id)
    if page is None:
        raise ReviewError(f"페이지가 없다: {stable_id}")

    res = result or lint_mod.run(store)
    findings = [f for f in res.findings if f.page == stable_id]
    blocking = [f for f in findings if f.code in BLOCKING_CODES]

    if decision == "approve":
        if blocking:
            raise ReviewError(
                "배포 차단 위반이 있어 승인할 수 없다: "
                + ", ".join(sorted({f.code for f in blocking}))
                + " — 사람이 넘길 수 있는 종류가 아니다. 먼저 고친다.")
        if not page.numeric_verified and not acknowledge_unverified:
            raise ReviewError(
                "수치 검산을 통과하지 못한 페이지다. 원문과 재계산 중 무엇이 맞는지 "
                "확인한 뒤 '미검산 인지' 를 명시해야 승인된다 (P2).")

    status = {"approve": "reviewed", "reject": "draft", "deprecate": "deprecated"}[decision]
    record = store.set_status(stable_id, status, actor=actor,
                              note=note or f"검토 결정: {decision}")

    entry = {
        "at": now_iso(),
        "stable_id": stable_id,
        "type": page.type,
        "version": page.version,
        "decision": decision,
        "status": status,
        "actor": actor,
        "note": note,
        "acknowledged_unverified": bool(acknowledge_unverified and not page.numeric_verified),
        "numeric_verified": page.numeric_verified,
        "content_hash": page.front_matter.get("content_hash", ""),
        "findings": sorted({f.code for f in findings}),
    }
    _append(store, entry)
    return {**entry, "log": record}


def stats(store: WikiStore) -> dict[str, Any]:
    rows = journal(store, limit=10_000)
    by_decision: dict[str, int] = {}
    actors: dict[str, int] = {}
    for r in rows:
        by_decision[r.get("decision", "")] = by_decision.get(r.get("decision", ""), 0) + 1
        actors[r.get("actor", "")] = actors.get(r.get("actor", ""), 0) + 1
    return {
        "records": len(rows),
        "by_decision": dict(sorted(by_decision.items())),
        "reviewers": dict(sorted(actors.items(), key=lambda kv: -kv[1])),
        "acknowledged_unverified": sum(1 for r in rows if r.get("acknowledged_unverified")),
        "last_at": rows[0]["at"] if rows else "",
    }
