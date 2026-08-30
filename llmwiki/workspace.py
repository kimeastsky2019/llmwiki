"""불러온 프로젝트(소스 폴더) 목록 관리.

config.yaml 에 적힌 프로젝트는 항상 `default` 로 존재하고, 뷰어에서 폴더를
불러오면 여기에 추가된다. 프로젝트마다 docs/ 와 index.json 을 따로 두므로
서로 산출물을 덮어쓰지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config

DEFAULT_ID = "default"

# 소스로 볼 확장자 (폴더 탐색기의 '읽을 만한 폴더인가' 힌트)
SOURCE_SUFFIXES = (".java", ".xml")

# 스캔에서 항상 빼는 디렉터리 이름
SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".idea", ".vscode",
    ".gradle", ".mvn", "target", "build", "out", "bin", "dist", "venv", ".venv",
}


@dataclass
class Project:
    id: str
    name: str
    roots: list[str]
    docs_dir: str
    index_file: str
    layers: list[dict[str, str]] = field(default_factory=list)
    builtin: bool = False
    added_at: str = ""
    parsed_at: str | None = None
    counts: dict[str, int] = field(default_factory=dict)
    # 분석 결과가 0건일 때 '대신 무엇이 있었는지' (survey())
    survey: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Registry:
    """projects.json 읽기/쓰기. 서버 스레드 여러 개에서 만지므로 락을 건다."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.file = cfg.workspace_dir / "projects.json"
        self._lock = threading.Lock()

    # --- 내부 ---
    def _builtin(self) -> Project:
        return Project(
            id=DEFAULT_ID,
            name=self.cfg.project_name,
            roots=[str(r) for r in self.cfg.source_roots],
            docs_dir=str(self.cfg.docs_dir),
            index_file=str(self.cfg.index_file),
            layers=self.cfg.layers,
            builtin=True,
        )

    def _read(self) -> dict[str, Any]:
        if not self.file.exists():
            return {"projects": [], "active": DEFAULT_ID}
        try:
            return json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"projects": [], "active": DEFAULT_ID}

    def _write(self, data: dict[str, Any]) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # --- 공개 ---
    def all(self) -> list[Project]:
        """config.yaml 프로젝트가 항상 첫 번째."""
        data = self._read()
        added = [Project(**p) for p in data.get("projects", [])]
        return [self._builtin(), *added]

    def get(self, project_id: str | None) -> Project:
        wanted = project_id or self.active_id()
        for p in self.all():
            if p.id == wanted:
                return p
        return self._builtin()

    def active_id(self) -> str:
        return self._read().get("active", DEFAULT_ID)

    def set_active(self, project_id: str) -> None:
        with self._lock:
            data = self._read()
            data["active"] = project_id
            self._write(data)

    def add(self, path: Path, name: str | None = None) -> Project:
        """폴더 하나를 새 프로젝트로 등록한다 (파싱은 하지 않는다)."""
        path = path.resolve()
        with self._lock:
            data = self._read()
            existing = {p["id"] for p in data.get("projects", [])} | {DEFAULT_ID}
            for raw in data.get("projects", []):
                if raw["roots"] == [str(path)]:
                    return Project(**raw)  # 같은 폴더는 다시 만들지 않는다

            pid = _unique_id(name or path.name, existing, path)
            home = self.cfg.workspace_dir / pid
            project = Project(
                id=pid,
                name=name or path.name,
                roots=[str(path)],
                docs_dir=str(home / "docs"),
                index_file=str(home / "index.json"),
                layers=[],
                added_at=datetime.now().isoformat(timespec="seconds"),
            )
            (home / "docs").mkdir(parents=True, exist_ok=True)
            data.setdefault("projects", []).append(project.to_dict())
            data["active"] = pid
            self._write(data)
            return project

    def update(self, project_id: str, **fields: Any) -> Project | None:
        with self._lock:
            data = self._read()
            for raw in data.get("projects", []):
                if raw["id"] == project_id:
                    raw.update(fields)
                    self._write(data)
                    return Project(**raw)
        # 기본 프로젝트는 config.yaml 이 원본이라 레지스트리에 쓰지 않는다
        return None

    def remove(self, project_id: str) -> bool:
        if project_id == DEFAULT_ID:
            return False
        with self._lock:
            data = self._read()
            before = len(data.get("projects", []))
            data["projects"] = [
                p for p in data.get("projects", []) if p["id"] != project_id
            ]
            if len(data["projects"]) == before:
                return False
            if data.get("active") == project_id:
                data["active"] = DEFAULT_ID
            self._write(data)
        return True

    def config_for(self, project: Project) -> Config:
        if project.builtin:
            return self.cfg
        return self.cfg.derive(
            name=project.name,
            source_roots=project.roots,
            docs_dir=project.docs_dir,
            index_file=project.index_file,
            layers=project.layers,
        )


def _unique_id(name: str, taken: set[str], path: Path | None = None) -> str:
    """폴더/프로젝트 이름 → URL 에 쓸 수 있는 id.

    한글 이름은 슬러그가 통째로 비어 'project' 하나로 뭉개진다. 그러면 서로
    다른 폴더가 project, project-2 … 로만 구분돼 목록에서 알아볼 수 없다.
    비었을 때는 경로 해시를 붙여 최소한 고유하게 만든다.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not base and path is not None:
        digest = hashlib.sha1(str(path).encode()).hexdigest()[:6]
        base = f"{re.sub(r'[^a-z0-9]+', '-', path.name.lower()).strip('-') or 'project'}-{digest}"
    base = base or "project"
    if base not in taken:
        return base
    for n in range(2, 1000):
        candidate = f"{base}-{n}"
        if candidate not in taken:
            return candidate
    raise RuntimeError("프로젝트 ID 를 만들 수 없습니다")


# --------------------------------------------------------------------------- #
# 폴더 탐색기
# --------------------------------------------------------------------------- #
# '이 폴더가 프로젝트 루트인가' 를 알려 주는 표식. 탐색기에서 배지로 보여 준다.
PROJECT_MARKERS = {
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "settings.gradle": "gradle",
    "build.xml": "ant",
    "WEB-INF": "webapp",
    ".git": "git",
    ".svn": "svn",
}


def list_dir(path: Path, roots: list[Path], *, limit: int = 500) -> dict[str, Any]:
    """하위 디렉터리 목록 + 각 디렉터리의 소스 개수·프로젝트 표식."""
    path = path.resolve()
    if not any(path == r or path.is_relative_to(r) for r in roots):
        raise PermissionError(str(path))
    if not path.is_dir():
        raise FileNotFoundError(str(path))

    entries: list[dict[str, Any]] = []
    try:
        with os.scandir(path) as it:
            children = sorted(
                (e for e in it if _is_visible_dir(e)), key=lambda e: e.name.lower()
            )
    except (PermissionError, OSError):
        children = []

    for child in children:
        if len(entries) >= limit:
            break
        entries.append({"name": child.name, "path": child.path, **probe(Path(child.path))})

    parent = path.parent
    can_up = path != parent and any(
        parent == r or parent.is_relative_to(r) for r in roots
    )
    return {
        "path": str(path),
        "name": path.name or str(path),
        "parent": str(parent) if can_up else None,
        # 브레드크럼용 — 루트 위로는 올라갈 수 없으므로 루트에서 잘라 준다
        "crumbs": _crumbs(path, roots),
        "entries": entries,
        # 지금 폴더는 '분석 대상' 후보라 더 깊이 센다
        "self": probe(path, cap=20_000),
    }


def quick_links(roots: list[Path]) -> list[dict[str, str]]:
    """탐색기 좌측 바로가기. roots 안에 실제로 있는 것만."""
    home = Path.home()
    candidates = [
        (home, "홈"),
        (home / "Desktop", "바탕화면"),
        (home / "Documents", "문서"),
        (home / "Downloads", "다운로드"),
        (home / "workspace", "workspace"),
        (home / "git", "git"),
        (home / "Projects", "Projects"),
    ]
    for root in roots:
        if root != home:
            candidates.insert(0, (root, root.name or str(root)))

    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for path, label in candidates:
        key = str(path)
        if key in seen or not path.is_dir():
            continue
        if not any(path == r or path.is_relative_to(r) for r in roots):
            continue
        seen.add(key)
        out.append({"label": label, "path": key})
    return out


def _is_visible_dir(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
            return False
    except OSError:
        return False
    return not entry.name.startswith(".") and entry.name not in SKIP_DIRS


def _crumbs(path: Path, roots: list[Path]) -> list[dict[str, str]]:
    base = next(
        (r for r in roots if path == r or path.is_relative_to(r)),
        Path(path.anchor),
    )
    crumbs = [{"label": base.name or str(base), "path": str(base)}]
    if path != base:
        for part in path.relative_to(base).parts:
            base = base / part
            crumbs.append({"label": part, "path": str(base)})
    return crumbs


def probe(path: Path, *, cap: int = 6000) -> dict[str, Any]:
    """.java / .xml 개수 + 하위 폴더 유무 + 프로젝트 표식.

    폴더 고르기 전에 '여기가 맞나' 보려는 용도라 cap 에서 멈춘다 — 정확한
    수치가 아니라 신호면 충분하다. Path.iterdir + is_dir 은 항목마다 stat 을
    부르지만 scandir 은 readdir 이 준 정보를 재사용해 훨씬 빠르다. 홈 디렉터리
    같은 큰 폴더에서 클릭 반응이 몇 초씩 밀리는 것을 막는 데 이 차이가 크다.
    """
    java = xml = 0
    seen = 0
    capped = 0
    has_dirs = False
    markers: list[str] = []

    def sweep(current: str, top: bool) -> list[str]:
        """한 디렉터리를 훑고 더 내려갈 하위 디렉터리를 돌려준다."""
        nonlocal java, xml, seen, capped, has_dirs
        nxt: list[str] = []
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if seen >= cap:
                        capped = 1
                        return nxt
                    try:
                        is_dir = not entry.is_symlink() and entry.is_dir(
                            follow_symlinks=False
                        )
                    except OSError:
                        continue
                    if top and entry.name in PROJECT_MARKERS:
                        markers.append(PROJECT_MARKERS[entry.name])
                    if is_dir:
                        if entry.name.startswith(".") or entry.name in SKIP_DIRS:
                            continue
                        if top:
                            has_dirs = True
                        nxt.append(entry.path)
                        continue
                    seen += 1
                    if entry.name.endswith(".java"):
                        java += 1
                    elif entry.name.endswith(".xml"):
                        xml += 1
        except (PermissionError, OSError, NotADirectoryError):
            pass
        return nxt

    stack = sweep(str(path), True)
    while stack and not capped:
        stack.extend(sweep(stack.pop(), False))

    return {
        "java": java,
        "xml": xml,
        "capped": capped,
        "has_dirs": has_dirs,
        "markers": sorted(set(markers)),
    }


def count_sources(path: Path, *, cap: int = 6000) -> dict[str, Any]:
    """예전 이름 — probe 로 위임한다."""
    return probe(path, cap=cap)


def survey(roots: list[Path], *, top: int = 6, cap: int = 60_000) -> dict[str, Any]:
    """폴더에 '무엇이 들어 있는지' 요약.

    분석 결과가 0건일 때 "아무 반응이 없다"로 보이지 않게 하려는 것이다.
    Java 가 없다면 대신 무엇이 있었는지 보여 줘야 사용자가 판단할 수 있다.
    """
    counts: dict[str, int] = {}
    files = 0
    skipped: set[str] = set()
    capped = False

    for root in roots:
        if capped or not root.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            drop = [d for d in dirnames if d in SKIP_DIRS or d.startswith(".")]
            skipped.update(drop)
            dirnames[:] = [d for d in dirnames if d not in drop]
            for name in filenames:
                if name.startswith("."):
                    continue
                files += 1
                if files > cap:
                    capped = True
                    break
                ext = Path(name).suffix.lower() or "(확장자 없음)"
                counts[ext] = counts.get(ext, 0) + 1
            if capped:
                break

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
    return {
        "files": files,
        "capped": capped,
        "by_ext": [{"ext": ext, "count": n} for ext, n in ranked],
        "skipped_dirs": sorted(skipped),
    }
