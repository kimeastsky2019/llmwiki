"""백그라운드 작업(파싱 · 명세서 생성) 추적.

큰 저장소는 파싱만 수십 초가 걸린다. 요청 안에서 다 처리하면 브라우저가
타임아웃되므로, 스레드에 던져 두고 상태만 폴링하게 한다.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from datetime import datetime
from typing import Any, Callable

_JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()

# 완료된 작업을 무한정 쌓아 두지 않는다
MAX_JOBS = 200


def create(kind: str, **extra: Any) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        if len(_JOBS) >= MAX_JOBS:
            for stale in sorted(_JOBS, key=lambda k: _JOBS[k]["started_at"])[:50]:
                if _JOBS[stale]["state"] != "running":
                    _JOBS.pop(stale, None)
        _JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "state": "running",
            "message": "",
            "result": None,
            "error": None,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            **extra,
        }
    return job_id


def update(job_id: str, **fields: Any) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job:
            job.update(fields)


def get(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def run(kind: str, work: Callable[[Callable[[str], None]], Any], **extra: Any) -> str:
    """work(progress) 를 스레드에서 실행한다. progress("메시지") 로 상태를 알린다."""
    job_id = create(kind, **extra)

    def target() -> None:
        try:
            result = work(lambda msg: update(job_id, message=msg))
            update(job_id, state="done", result=result, message="")
        except Exception as exc:  # noqa: BLE001
            update(
                job_id,
                state="failed",
                error=str(exc) or exc.__class__.__name__,
                trace=traceback.format_exc(limit=3),
            )

    threading.Thread(target=target, daemon=True, name=f"llmwiki-{kind}").start()
    return job_id
