"""브라우저에서 올린 소스를 서버 디스크에 푼다.

받는 형태는 두 가지다.
  - 폴더 통째 (input webkitdirectory) → 파일마다 상대경로가 함께 온다
  - ZIP 한 개 → 서버에서 푼다

둘 다 '클라이언트가 준 경로'를 그대로 믿으면 안 된다. ../../etc/passwd 같은
항목 하나로 서버 파일이 덮인다(ZIP 의 경우 zip slip). 그래서 경로는 전부
sanitize 를 거치고, 마지막에 실제 해석된 경로가 목적지 안인지 다시 본다.
"""

from __future__ import annotations

import shutil
import threading
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO, Iterable

from ..workspace import SKIP_DIRS

# 저장을 허용하는 확장자. 소스와 그 주변 설정까지만 받는다.
# 허용목록으로 두는 이유: 실행파일·아카이브가 서버에 남지 않게 하려는 것이다.
ALLOWED_SUFFIXES = {
    ".java", ".xml", ".py", ".sql", ".jsp", ".js", ".ts", ".tsx", ".jsx",
    ".properties", ".yml", ".yaml", ".json", ".html", ".htm", ".css", ".scss",
    ".md", ".txt", ".gradle", ".cfg", ".ini", ".conf", ".sh", ".bat",
    ".c", ".h", ".cpp", ".cs", ".go", ".rb", ".php", ".kt", ".scala", ".groovy",
}

# 한도. 초과분은 조용히 버리지 않고 결과에 담아 화면에 알린다.
MAX_FILES = 20_000
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024


@dataclass
class UploadStats:
    files: int = 0
    bytes: int = 0
    skipped: int = 0
    reasons: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, object]:
        return {
            "files": self.files,
            "bytes": self.bytes,
            "skipped": self.skipped,
            "reasons": sorted(self.reasons),
        }


class UploadError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 실패."""


def safe_relpath(raw: str) -> str | None:
    """업로드가 준 경로를 저장 가능한 상대경로로. 못 쓰면 None.

    Windows 백슬래시, 절대경로, 드라이브 문자, '..' 를 전부 걷어낸다.
    """
    if not raw:
        return None
    text = raw.replace("\\", "/").strip()
    # "C:/src/A.java" 같은 절대경로 → 드라이브 문자 제거
    if len(text) > 1 and text[1] == ":":
        text = text[2:]
    parts: list[str] = []
    for part in PurePosixPath(text).parts:
        if part in ("", ".", "/"):
            continue
        if part == "..":
            return None
        if part.startswith("."):
            return None  # .git, .env 등은 받지 않는다
        if part in SKIP_DIRS:
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def strip_common_root(paths: list[str]) -> list[str]:
    """모든 경로가 같은 최상위 폴더를 공유하면 그 한 겹을 벗긴다.

    폴더를 통째로 올리면 경로가 'myproj/src/...' 로 온다. 그대로 두면
    소스 루트가 한 단계 위가 돼 트리에 의미 없는 마디가 하나 생긴다.
    """
    tops = {p.split("/", 1)[0] for p in paths}
    if len(tops) != 1:
        return paths
    stripped = [p.split("/", 1)[1] for p in paths if "/" in p]
    # 최상위에 파일만 덩그러니 있는 경우(벗기면 이름이 사라진다)는 그대로 둔다
    return stripped if len(stripped) == len(paths) else paths


def _target(dest: Path, rel: str) -> Path | None:
    """dest 안으로 확정된 절대경로. 밖으로 나가면 None."""
    path = (dest / rel).resolve()
    return path if path.is_relative_to(dest) else None


def _accept(rel: str, stats: UploadStats) -> bool:
    if Path(rel).suffix.lower() not in ALLOWED_SUFFIXES:
        stats.skipped += 1
        stats.reasons.add("확장자 제외")
        return False
    return True


@dataclass
class Incoming:
    """저장할 파일 하나 — 열린 스트림과 클라이언트가 준 경로."""

    rel: str
    stream: IO[bytes]
    size: int | None = None


def store_files(
    dest: Path, items: Iterable[Incoming], *, strip_root: bool = True, base: UploadStats | None = None
) -> UploadStats:
    """폴더 업로드를 디스크에 쓴다.

    strip_root: 공통 최상위를 벗길지. 나눠 보내는(배치) 업로드는 한 번에 전체
    경로를 볼 수 없으므로 클라이언트가 이미 벗겨서 보낸다 — 그때는 False.
    base: 누적 통계. 배치마다 한도(총량)를 이어서 세기 위한 것이다.
    """
    stats = base if base is not None else UploadStats()
    pending = [(i, safe_relpath(i.rel)) for i in items]
    usable = [(i, r) for i, r in pending if r]
    stats.skipped += len(pending) - len(usable)
    if len(pending) != len(usable):
        stats.reasons.add("숨김·빌드 폴더 제외")

    rels = [r for _, r in usable]
    if strip_root:
        rels = strip_common_root(rels)
    dest.mkdir(parents=True, exist_ok=True)

    for (item, _), rel in zip(usable, rels):
        if stats.files >= MAX_FILES:
            stats.skipped += 1
            stats.reasons.add(f"파일 수 상한 {MAX_FILES} 초과")
            continue
        if not _accept(rel, stats):
            continue
        target = _target(dest, rel)
        if target is None:
            stats.skipped += 1
            stats.reasons.add("경로 이탈 차단")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        written = _copy_capped(item.stream, target, stats)
        if written is None:
            continue
        stats.files += 1
        stats.bytes += written

    # 배치(base 전달)에서는 이 묶음이 통째로 걸러질 수 있다 — 정상이다.
    # 전체가 비었는지는 세션을 마칠 때 본다.
    if stats.files == 0 and base is None:
        raise UploadError(no_files_message())
    return stats


def no_files_message() -> str:
    return (
        "저장할 소스 파일이 없습니다. "
        f"허용 확장자: {', '.join(sorted(ALLOWED_SUFFIXES)[:12])} …"
    )


def extract_zip(dest: Path, stream: IO[bytes]) -> UploadStats:
    """ZIP 업로드를 푼다. 압축률을 이용한 폭탄도 총량으로 막는다."""
    stats = UploadStats()
    try:
        zf = zipfile.ZipFile(stream)
    except zipfile.BadZipFile as exc:
        raise UploadError(f"ZIP 파일을 읽을 수 없습니다: {exc}") from exc

    with zf:
        entries = [e for e in zf.infolist() if not e.is_dir()]
        pending = [(e, safe_relpath(e.filename)) for e in entries]
        usable = [(e, r) for e, r in pending if r]
        stats.skipped += len(pending) - len(usable)
        if len(pending) != len(usable):
            stats.reasons.add("숨김·빌드 폴더 제외")

        rels = strip_common_root([r for _, r in usable])
        dest.mkdir(parents=True, exist_ok=True)

        for (entry, _), rel in zip(usable, rels):
            if stats.files >= MAX_FILES:
                stats.skipped += 1
                stats.reasons.add(f"파일 수 상한 {MAX_FILES} 초과")
                continue
            # 심볼릭 링크 항목(상위 16비트가 파일 모드)은 풀지 않는다.
            # 링크를 그대로 만들면 루트 밖을 가리키게 할 수 있다.
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                stats.skipped += 1
                stats.reasons.add("심볼릭 링크 제외")
                continue
            if not _accept(rel, stats):
                continue
            target = _target(dest, rel)
            if target is None:
                stats.skipped += 1
                stats.reasons.add("경로 이탈 차단")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(entry) as src:
                written = _copy_capped(src, target, stats)
            if written is None:
                continue
            stats.files += 1
            stats.bytes += written

    if stats.files == 0:
        raise UploadError("ZIP 안에서 저장할 소스 파일을 찾지 못했습니다.")
    return stats


# --------------------------------------------------------------------------- #
# 나눠 보내는 업로드 (세션)
#
# 폴더 하나를 한 요청에 담으면, 브라우저가 파일 수백 개를 디스크에서 읽어
# multipart 본문을 다 만들 때까지 첫 바이트가 나가지 않는다. 그 사이 nginx 의
# client_body_timeout 이 먼저 끝나 408 로 끊긴다. 작게 나눠 보내면 각 요청이
# 짧게 끝나고, 실패한 묶음만 다시 보낼 수 있다.
# --------------------------------------------------------------------------- #
SESSION_TTL_SEC = 3600


@dataclass
class Session:
    id: str
    name: str
    dest: Path
    stats: UploadStats
    touched: float


class Sessions:
    """진행 중인 업로드들. 워커가 하나이므로 메모리에 둔다 (jobs 와 같은 방식)."""

    def __init__(self) -> None:
        self._items: dict[str, Session] = {}
        self._lock = threading.Lock()

    def start(self, root: Path, name: str, *, now: float) -> Session:
        self._sweep(root, now)
        with self._lock:
            sid = uuid.uuid4().hex[:12]
            session = Session(
                id=sid,
                name=name,
                dest=unique_dir(root, name),
                stats=UploadStats(),
                touched=now,
            )
            session.dest.mkdir(parents=True, exist_ok=True)
            self._items[sid] = session
            return session

    def get(self, sid: str, *, now: float) -> Session:
        with self._lock:
            session = self._items.get(sid)
            if session is None:
                raise UploadError(
                    "업로드 세션을 찾을 수 없습니다. 오래 방치됐거나 서버가 재시작됐습니다. "
                    "다시 시도하십시오."
                )
            session.touched = now
            return session

    def pop(self, sid: str, *, now: float) -> Session:
        session = self.get(sid, now=now)
        with self._lock:
            self._items.pop(sid, None)
        return session

    def _sweep(self, root: Path, now: float) -> None:
        """버려진 세션의 임시 폴더를 치운다. 안 그러면 디스크에 쌓이기만 한다."""
        with self._lock:
            stale = [s for s in self._items.values() if now - s.touched > SESSION_TTL_SEC]
            for s in stale:
                self._items.pop(s.id, None)
        for s in stale:
            discard(s.dest, root)


def _copy_capped(src: IO[bytes], target: Path, stats: UploadStats) -> int | None:
    """한도를 넘으면 쓰다 만 파일을 지우고 None. 넘긴 바이트 수를 돌려준다.

    선언된 크기가 아니라 실제로 읽은 양으로 센다. ZIP 헤더의 file_size 는
    믿을 수 없고(압축 폭탄), 업로드 스트림도 마찬가지다.
    """
    remaining_total = MAX_TOTAL_BYTES - stats.bytes
    limit = min(MAX_FILE_BYTES, remaining_total)
    written = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = src.read(256 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise _TooBig()
                out.write(chunk)
    except _TooBig:
        target.unlink(missing_ok=True)
        stats.skipped += 1
        stats.reasons.add(
            "총 용량 상한 초과" if remaining_total < MAX_FILE_BYTES else "파일 크기 상한 초과"
        )
        return None
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise UploadError(f"파일을 저장하지 못했습니다: {exc}") from exc
    return written


class _TooBig(Exception):
    pass


def unique_dir(base: Path, name: str) -> Path:
    """base/name — 이미 있으면 -2, -3 … 을 붙인다."""
    slug = "".join(c if c.isalnum() or c in "-_." else "-" for c in name).strip("-.")
    slug = slug or "upload"
    candidate = base / slug
    for n in range(2, 1000):
        if not candidate.exists():
            return candidate
        candidate = base / f"{slug}-{n}"
    raise UploadError("업로드 폴더 이름을 정할 수 없습니다.")


def discard(path: Path, root: Path) -> None:
    """실패한 업로드를 치운다. root 밖은 절대 건드리지 않는다."""
    if path.is_dir() and path.is_relative_to(root) and path != root:
        shutil.rmtree(path, ignore_errors=True)
