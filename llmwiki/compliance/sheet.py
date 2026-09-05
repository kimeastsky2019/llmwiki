"""평가표 — 관리자가 만드는 자가진단 설문.

회의에서 나온 그대로다.

  "평가 시트를 만든 어드민이 있는 거예요. 질문 등록하면 이제 평가 지표 나온
   거고 5개가 있다 그러면은 매우 불만족 만족 보통 ... 라디오 버튼으로 할 건지
   아니면 중복이면 체크박스로 할 건지 이런 거에서 이제 설문 자체를 만드는 기능"

`기준 관리`(Control·TestProcedure)와 다른 축이다. 저쪽은 **기계가 증적으로
확인하는 통제**이고, 여기는 **사람이 채우는 질문지**다. 둘을 한 곳에 합치면
"이건 증적으로 확인되나, 아니면 담당자가 답하나" 가 화면에서 흐려진다.

지침이 바뀔 것을 전제로 만든다 — 회의: "지침 자체가 바뀔 수 있다는 전제로 ...
나중에 좀 타이트해지면 그 지표만 업데이트하면 되겠어." 그래서 표는 버전을
갖고, 고치면 새 버전이 쌓이며 옛 버전은 지워지지 않는다. 이미 그 표로 답한
기록이 어느 버전 질문에 답한 것인지 알 수 있어야 한다.

★ **발행은 아직 결재를 거치지 않는다.** 이 저장소의 다른 기준(통제·지표)은
  전부 커밋 결재를 지나는데 평가표는 관리자가 바로 발행한다. 회의가 그렇게
  정한 것이라 그대로 두되, 그 사실을 화면과 여기에 적어 둔다 — 나중에 결재를
  붙일 때 무엇이 빠져 있었는지 알아야 한다.
"""

from __future__ import annotations

import re
from typing import Any

from .store import Store, now_iso

SHEETS = "sheets.jsonl"

#: 응답 유형. 회의에서 예로 든 것(라디오·체크박스)에 척도·서술·예아니오를 더했다.
#: 닫힌 집합이다 — 화면이 그릴 수 있는 것만 있어야 한다.
KINDS: tuple[str, ...] = ("single", "multi", "scale", "yesno", "text")

#: 척도의 기본 눈금. 관리자가 바꿀 수 있고, 바꾸면 그 값이 표에 저장된다.
DEFAULT_SCALE = ["매우 그렇다", "그렇다", "보통", "아니다", "전혀 아니다"]

DRAFT = "draft"
PUBLISHED = "published"


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9가-힣]+", "-", text).strip("-").lower()[:40]


def _read(store: Store) -> list[dict[str, Any]]:
    from .store import _read_jsonl

    return _read_jsonl(store.root / SHEETS)


def _append(store: Store, record: dict[str, Any]) -> None:
    from .store import _append_jsonl

    _append_jsonl(store.root / SHEETS, [record])


def latest(store: Store) -> dict[str, dict[str, Any]]:
    """표 ID 별 최신 레코드. 버전은 레코드 안에 있고 이력은 파일에 남는다."""
    out: dict[str, dict[str, Any]] = {}
    for rec in _read(store):
        sid = rec.get("sheet_id")
        if sid:
            out[sid] = rec
    return out


def history(store: Store, sheet_id: str) -> list[dict[str, Any]]:
    return [r for r in _read(store) if r.get("sheet_id") == sheet_id]


def validate(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """질문을 정리한다. 화면이 그릴 수 없는 것은 여기서 막는다."""
    out: list[dict[str, Any]] = []
    for i, raw in enumerate(questions, start=1):
        text = str(raw.get("text", "")).strip()
        if not text:
            raise ValueError(f"{i}번 질문에 내용이 없다")
        kind = str(raw.get("kind", "yesno"))
        if kind not in KINDS:
            raise ValueError(f"{i}번 질문의 응답 유형이 잘못됐다: {kind}")

        options = [str(o).strip() for o in (raw.get("options") or []) if str(o).strip()]
        if kind in ("single", "multi") and len(options) < 2:
            raise ValueError(f"{i}번 질문({kind})에는 보기가 둘 이상 있어야 한다")
        if kind == "scale" and not options:
            options = list(DEFAULT_SCALE)
        if kind in ("yesno", "text"):
            options = []

        # 어느 답이 위험 신호인가. 이것이 없으면 답을 32항목으로 옮길 수 없다 —
        # "측정했는가?" 는 아니오가 위험이고 "민감정보를 쓰는가?" 는 예가 위험이라,
        # 방향을 사람이 정해 주지 않으면 기계가 반대로 읽는다.
        # ★ 비워 두면 후보를 만들지 않는다. 찍는 것보다 안 만드는 쪽이 낫다.
        risk_when = raw.get("risk_when")
        if kind == "yesno":
            risk_when = risk_when if risk_when in ("yes", "no") else ""
        elif kind in ("single", "multi", "scale"):
            picked = [str(o) for o in (risk_when or []) if str(o) in options]
            risk_when = picked
        else:
            risk_when = ""

        item_no = raw.get("item_no")
        try:
            item_no = int(item_no) if item_no not in (None, "") else None
        except (TypeError, ValueError):
            item_no = None
        if item_no is not None and not 1 <= item_no <= 32:
            raise ValueError(f"{i}번 질문의 위험 항목 번호가 범위 밖이다: {item_no}")

        out.append({
            "no": i,
            "text": text,
            "kind": kind,
            "options": options,
            "required": bool(raw.get("required", True)),
            "help": str(raw.get("help", "")).strip(),
            # 32항목과 이어 두면 자가진단 결과가 어느 위험 항목의 근거인지 남는다.
            "item_no": item_no,
            "risk_when": risk_when,
            # sLM 초안에서 온 질문인지. 관리자가 손대면 화면이 이 표시를 지운다.
            "drafted_by_slm": bool(raw.get("drafted_by_slm")),
        })
    return out


def save(
    store: Store,
    *,
    sheet_id: str = "",
    title: str,
    questions: list[dict[str, Any]],
    by: str,
    note: str = "",
    owner_role: str = "",
) -> dict[str, Any]:
    """표를 만들거나 고친다. 고치면 새 버전이 쌓이고 옛 버전은 남는다."""
    label = title.strip()
    if not label:
        raise ValueError("표 이름이 필요하다")
    editor = by.strip()
    if not editor:
        raise ValueError("작성자가 필요하다")

    items = validate(questions)
    known = latest(store)
    sid = (sheet_id or f"sh-{_slug(label)}").strip()
    prev = known.get(sid)
    record = {
        "sheet_id": sid,
        "title": label,
        "version": (prev["version"] + 1) if prev else 1,
        # 고치면 다시 초안으로 내린다. 발행본을 조용히 바꾸면, 이미 그 표로 답한
        # 사람이 무엇에 답했는지 알 수 없게 된다.
        "status": DRAFT,
        "owner_role": owner_role or (prev or {}).get("owner_role", ""),
        "questions": items,
        "note": note,
        "saved_by": editor,
        "saved_at": now_iso(),
        "published_by": "",
        "published_at": "",
    }
    _append(store, record)
    return record


def publish(store: Store, sheet_id: str, *, by: str) -> dict[str, Any]:
    """발행한다 — 이 순간부터 이 표로 자가진단을 받는다.

    ★ 지금은 결재를 거치지 않는다. 회의에서 관리자가 직접 만드는 것으로 정한
      것이라 그대로 두었지만, 이 저장소의 다른 기준은 전부 커밋 결재를 지난다.
      나중에 결재를 붙일 자리가 여기다.
    """
    record = latest(store).get(sheet_id)
    if record is None:
        raise KeyError(f"평가표를 찾을 수 없다: {sheet_id}")
    if not record["questions"]:
        raise ValueError("질문이 없는 표는 발행할 수 없다")
    agent = by.strip()
    if not agent:
        raise ValueError("발행자가 필요하다")

    updated = {
        **record,
        "status": PUBLISHED,
        "published_by": agent,
        "published_at": now_iso(),
    }
    _append(store, updated)
    return updated
