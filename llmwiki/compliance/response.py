"""자가진단 응답 — 담당자가 평가표를 채운 결과.

평가표(`sheet.py`)를 만들어 두기만 하면 쓸 곳이 없다. 여기가 그 표를 실제로
채우고, 채운 답이 32항목 **후보**로 이어지는 자리다.

세 가지를 지킨다.

1. **어느 버전에 답했는지 남긴다.** 표는 고칠 수 있고 고치면 새 버전이 된다.
   버전을 안 남기면 나중에 "이 사람은 무엇에 답한 것인가" 를 알 수 없다.
2. **판정하지 않는다.** 답에서 나오는 것은 전부 `candidate` 다. 위험 식별
   Yes/No 는 위험등급 산정 화면에서 사람이 누르고, 점수는 룰이 계산한다.
3. **방향을 찍지 않는다.** 질문에 `risk_when` 이 없으면 후보를 만들지 않는다.
   "측정했는가?" 는 아니오가 위험이고 "민감정보를 쓰는가?" 는 예가 위험이라,
   방향을 모르면 반대로 읽는다. 반대로 읽은 후보는 없느니만 못하다.
"""

from __future__ import annotations

from typing import Any

from . import riskassess
from .store import Store, now_iso

RESPONSES = "responses.jsonl"


def _read(store: Store) -> list[dict[str, Any]]:
    from .store import _read_jsonl

    return _read_jsonl(store.root / RESPONSES)


def _append(store: Store, record: dict[str, Any]) -> None:
    from .store import _append_jsonl

    _append_jsonl(store.root / RESPONSES, [record])


def latest(store: Store) -> dict[str, dict[str, Any]]:
    """(표, 서비스) 별 최신 응답. 다시 답하면 새 레코드가 쌓이고 옛것은 남는다."""
    out: dict[str, dict[str, Any]] = {}
    for rec in _read(store):
        key = f"{rec.get('sheet_id')}::{rec.get('service_uuid')}"
        out[key] = rec
    return out


def history(store: Store, sheet_id: str, service_uuid: str) -> list[dict[str, Any]]:
    return [r for r in _read(store)
            if r.get("sheet_id") == sheet_id and r.get("service_uuid") == service_uuid]


def _is_risk(question: dict[str, Any], answer: Any) -> bool:
    """이 답이 위험 신호인가. 방향(`risk_when`)이 없으면 언제나 아니다."""
    when = question.get("risk_when")
    if not when:
        return False

    kind = question.get("kind")
    if kind == "yesno":
        # 답은 "yes" / "no" 로 온다.
        return str(answer) == str(when)
    if kind in ("single", "scale"):
        return str(answer) in when
    if kind == "multi":
        picked = {str(a) for a in (answer or [])}
        return bool(picked & set(when))
    return False


def candidates(sheet_rec: dict[str, Any], answers: dict[str, Any]) -> list[dict[str, Any]]:
    """답 → 32항목 후보. `codehints`·`dataprofile` 과 같은 규약이다."""
    labels = {i["no"]: f"{i['lv1']} > {i['lv3']}" for i in riskassess.items()}
    out: list[dict[str, Any]] = []
    for q in sheet_rec.get("questions", []):
        item_no = q.get("item_no")
        if not item_no:
            continue
        answer = answers.get(str(q["no"]))
        if answer in (None, "", []):
            continue
        if not _is_risk(q, answer):
            continue
        shown = ", ".join(str(a) for a in answer) if isinstance(answer, list) else str(answer)
        if q["kind"] == "yesno":
            shown = "예" if shown == "yes" else "아니오"
        out.append({
            "item_no": item_no,
            "label": labels.get(item_no, ""),
            "confidence": "candidate",
            "because": f"{q['no']}번 「{q['text']}」 → {shown}",
            "source": f"자가진단 「{sheet_rec['title']}」 v{sheet_rec['version']}",
        })
    return out


def save(
    store: Store,
    *,
    sheet_rec: dict[str, Any],
    service_uuid: str,
    answers: dict[str, Any],
    by: str,
    note: str = "",
) -> dict[str, Any]:
    """응답을 남긴다. 표의 버전을 함께 박는다."""
    agent = by.strip()
    if not agent:
        raise ValueError("응답자가 필요하다")
    if not service_uuid.strip():
        raise ValueError("대상 서비스가 필요하다")
    if sheet_rec.get("status") != "published":
        raise ValueError("발행된 표에만 답할 수 있다")

    missing = [
        q["no"] for q in sheet_rec["questions"]
        if q.get("required") and answers.get(str(q["no"])) in (None, "", [])
    ]
    if missing:
        raise ValueError("필수 질문에 답하지 않았다: " + ", ".join(f"{n}번" for n in missing))

    found = candidates(sheet_rec, answers)
    record = {
        "sheet_id": sheet_rec["sheet_id"],
        "sheet_title": sheet_rec["title"],
        # ★ 어느 버전에 답했는지. 표가 바뀌어도 이 답의 뜻은 바뀌지 않는다.
        "sheet_version": sheet_rec["version"],
        "service_uuid": service_uuid,
        "answers": answers,
        "candidates": found,
        "answered_by": agent,
        "answered_at": now_iso(),
        "note": note,
    }
    _append(store, record)
    return record
