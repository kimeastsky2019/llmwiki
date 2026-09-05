"""프로젝트 결재 — 계획 승인과 결과 승인, 두 차례.

회의(2026-09-05)에서 정해진 것을 그대로 옮긴다.

  · **두 차례의 승인이 있다.** "AI 윤리위원회에서 이제 계획을 승인할 거고
    결과에 대한 승인 두 차례의 승인이 있는데"
  · **등급이 승인권자를 정한다.** "고위험일 때는 윤리위원회 승인을 받아야 되고
    저중위험일 때는 그냥 거버넌스 담당자가 승인을 하면 되는 거고"
  · **고위험은 제3자 검증을 거친다.** "고위험 같은 경우에는 이걸로 커버하는 게
    아니라 제3자 검증을 또 거치는 거고"
  · **결재는 이 시스템에서 한다.** "AI 위험에 대한 결재 승인은 다 이 시스템에서
    한다" — IT 포털 ITSM 결재를 타지 않는다.

기준 변경 결재(`changeset.py`)와는 다른 것이다. 저쪽은 *무엇으로 잴 것인가*를
바꾸는 결재이고, 여기는 *이 서비스를 내보내도 되는가*를 묻는 결재다. 두 개를
한 테이블에 합치면 "기준이 바뀌었다" 와 "서비스가 승인됐다" 가 같은 줄에 서서,
감사에서 무엇을 물어도 답이 섞인다.

★ 등급은 여기서 계산하지 않는다. `riskassess` 가 낸 등급을 받아 쓰기만 한다 —
  승인권자를 정하는 값이 결재함에서 다시 계산되면 두 곳이 어긋날 수 있다.
"""

from __future__ import annotations

import re
from typing import Any

from .store import Store, now_iso

APPROVALS = "approvals.jsonl"

#: 결재의 종류. 순서가 있다 — 계획이 승인돼야 결과를 올릴 수 있다.
PLAN = "plan"
RESULT = "result"
KINDS: tuple[str, ...] = (PLAN, RESULT)

#: 상태
PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"

#: 고위험으로 보는 등급 키. 이 둘만 윤리위원회로 간다.
HIGH_KEYS: frozenset[str] = frozenset({"high", "unacceptable"})

#: 승인권자 역할. 화면의 역할 코드와 같은 문자열을 쓴다 — 사내 포털과 연동되면
#: 로그인 권한이 이 값으로 내려오고, 서버가 같은 코드로 판단한다.
COMMITTEE = "committee"
GOVERNANCE = "governance"
VERIFIER = "verifier"


def approver_role(grade_key: str) -> str:
    """이 등급의 승인권자는 누구인가. 회의에서 정해진 유일한 분기다."""
    return COMMITTEE if str(grade_key or "").lower() in HIGH_KEYS else GOVERNANCE


def needs_verification(grade_key: str) -> bool:
    """제3자 검증이 필요한가. 고위험만이다."""
    return str(grade_key or "").lower() in HIGH_KEYS


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()[:40]


def _read(store: Store) -> list[dict[str, Any]]:
    from .store import _read_jsonl  # 저장소의 append-only 규약을 그대로 쓴다

    return _read_jsonl(store.root / APPROVALS)


def _append(store: Store, record: dict[str, Any]) -> None:
    from .store import _append_jsonl

    _append_jsonl(store.root / APPROVALS, [record])


def latest(store: Store) -> dict[str, dict[str, Any]]:
    """ID 별 최신 상태. 이력은 남고 최신 레코드가 현재 상태다 (ChangeSet 과 같은 규약)."""
    out: dict[str, dict[str, Any]] = {}
    for rec in _read(store):
        rid = rec.get("approval_id")
        if rid:
            out[rid] = rec
    return out


def history(store: Store) -> list[dict[str, Any]]:
    return _read(store)


def of_service(store: Store, service_uuid: str) -> list[dict[str, Any]]:
    return sorted(
        (r for r in latest(store).values() if r.get("service_uuid") == service_uuid),
        key=lambda r: str(r.get("requested_at", "")),
    )


def request(
    store: Store,
    *,
    service_uuid: str,
    kind: str,
    grade_key: str,
    grade_label: str = "",
    by: str,
    note: str = "",
) -> dict[str, Any]:
    """결재를 상신한다.

    계획이 승인되기 전에 결과를 올릴 수 없다. 순서를 코드가 막지 않으면
    "검증도 안 했는데 결과 승인이 났다" 는 상태를 만들 수 있다.
    """
    if kind not in KINDS:
        raise ValueError(f"결재 종류는 {KINDS} 중 하나여야 한다")
    requester = by.strip()
    if not requester:
        raise ValueError("상신자가 필요하다")
    if not service_uuid.strip():
        raise ValueError("대상 서비스가 필요하다")

    mine = of_service(store, service_uuid)
    if any(r["kind"] == kind and r["status"] == PENDING for r in mine):
        raise ValueError("같은 종류의 결재가 이미 대기 중이다")
    if kind == RESULT:
        plan_ok = any(r["kind"] == PLAN and r["status"] == APPROVED for r in mine)
        if not plan_ok:
            raise ValueError("계획 승인이 먼저다 — 계획이 승인돼야 결과를 올릴 수 있다")

    seq = len([r for r in mine if r["kind"] == kind]) + 1
    record = {
        "approval_id": f"ap_{_slug(service_uuid)}_{kind}_{seq}",
        "service_uuid": service_uuid,
        "kind": kind,
        "grade_key": grade_key,
        "grade_label": grade_label,
        "approver_role": approver_role(grade_key),
        "needs_verification": needs_verification(grade_key) and kind == RESULT,
        "verification": None,
        "status": PENDING,
        "requested_by": requester,
        "requested_at": now_iso(),
        "note": note,
        "decided_by": "",
        "decided_at": "",
        "decision_note": "",
    }
    _append(store, record)
    return record


def file_verification(
    store: Store, approval_id: str, *, by: str, result: str, note: str = "",
) -> dict[str, Any]:
    """제3자 검증 결과를 등록한다. 사외 기관이 하는 일이라 승인과 분리한다.

    검증 결과를 등록하는 것은 **승인이 아니다.** 결과를 남길 뿐이고, 승인은
    여전히 윤리위원회가 한다. 둘을 합치면 사외 기관이 승인권을 갖게 된다.
    """
    record = latest(store).get(approval_id)
    if record is None:
        raise KeyError(f"결재를 찾을 수 없다: {approval_id}")
    if not record.get("needs_verification"):
        raise ValueError("제3자 검증이 필요한 건이 아니다 (고위험 결과 승인만 해당)")
    if record["status"] != PENDING:
        raise ValueError("이미 결정된 건에는 검증 결과를 붙일 수 없다")
    if result not in ("pass", "fail"):
        raise ValueError("검증 결과는 pass 또는 fail 이어야 한다")
    agent = by.strip()
    if not agent:
        raise ValueError("검증기관이 필요하다")

    updated = {
        **record,
        "verification": {
            "result": result, "by": agent, "at": now_iso(), "note": note,
        },
    }
    _append(store, updated)
    return updated


def decide(
    store: Store, approval_id: str, *, by: str, role: str, approve: bool, note: str = "",
) -> dict[str, Any]:
    """승인하거나 반려한다.

    막는 것이 셋이다.

    1. **등급이 정한 승인권자만 결정한다.** 고위험 건을 거버넌스 담당자가
       승인해 버리면 회의에서 정한 분기가 무의미해진다.
    2. **상신자는 자기 건을 승인할 수 없다.** 목업의 '역할 분리' 그대로다 —
       한 사람이 올리고 한 사람이 승인해야 결재라고 부를 수 있다.
    3. **고위험 결과 승인은 제3자 검증 결과가 있어야 한다.** 검증 없이 승인이
       나면 회의가 말한 고위험 경로가 그냥 뚫린다.
    """
    record = latest(store).get(approval_id)
    if record is None:
        raise KeyError(f"결재를 찾을 수 없다: {approval_id}")
    if record["status"] != PENDING:
        raise ValueError("이미 결정된 건이다")

    agent = by.strip()
    if not agent:
        raise ValueError("결재자가 필요하다")
    if role != record["approver_role"]:
        raise PermissionError(
            f"이 건의 승인권자는 '{record['approver_role']}' 다 — '{role}' 은 결정할 수 없다"
        )
    if agent == record["requested_by"]:
        raise PermissionError("상신자는 자기 건을 승인할 수 없다")
    if approve and record.get("needs_verification"):
        got = record.get("verification") or {}
        if got.get("result") != "pass":
            raise ValueError("고위험 결과 승인은 제3자 검증 통과가 먼저다")

    updated = {
        **record,
        "status": APPROVED if approve else REJECTED,
        "decided_by": agent,
        "decided_at": now_iso(),
        "decision_note": note,
    }
    _append(store, updated)
    return updated


def gate(store: Store, service_uuid: str) -> dict[str, Any]:
    """이 서비스가 지금 어느 문 앞에 서 있는가.

    IT 포털이 물어볼 값이기도 하다 — 회의: "승인 여부를 체크하게 되면은 IT
    포털에서 이행 갈 수 있는 버튼이 활성화가 되는 거죠."
    """
    mine = of_service(store, service_uuid)
    def has(kind: str, status: str) -> bool:
        return any(r["kind"] == kind and r["status"] == status for r in mine)

    plan_done = has(PLAN, APPROVED)
    result_done = has(RESULT, APPROVED)
    return {
        "service_uuid": service_uuid,
        "plan": APPROVED if plan_done else (PENDING if has(PLAN, PENDING) else ""),
        "result": APPROVED if result_done else (PENDING if has(RESULT, PENDING) else ""),
        # 이 한 값이 IT 포털의 '이행' 버튼을 연다.
        "deployable": plan_done and result_done,
        "approvals": mine,
    }
