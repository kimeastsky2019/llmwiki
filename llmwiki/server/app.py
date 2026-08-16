"""FastAPI 뷰어 서버."""

from __future__ import annotations

import fnmatch
import os
import shutil
import threading
import urllib.parse
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ..config import Config, load_config
from ..docgen import generate_all
from ..i18n import msg, normalize
from ..llm import check as check_provider
from ..indexer import load_index, save_index, scan
from ..parsers.graph import impact_of
from ..workspace import (
    DEFAULT_ID,
    SKIP_DIRS,
    Project,
    Registry,
    list_dir,
    quick_links,
    survey,
)
from . import jobs
from .excel import build_workbook, safe_filename
from .search import DocStore, search as run_search
from .upload import (
    Incoming,
    UploadError,
    discard,
    extract_zip,
    store_files,
    unique_dir,
)

CONFIG_PATH = os.environ.get("LLMWIKI_CONFIG", "config.yaml")
cfg = load_config(CONFIG_PATH)
registry = Registry(cfg)

app = FastAPI(title=f"{cfg.project_name} — LLMWiki")

# 소스 열람 한도 — 뷰어가 브라우저를 멈추게 하지 않도록 자른다
MAX_SOURCE_BYTES = 2_000_000
MAX_TREE_FILES = 20_000

# 소스 브라우저에서 감출 것들 (VCS 메타·빌드 산출물·바이너리)
HIDDEN_DIRS = {".git", ".svn", ".hg", "node_modules", "__pycache__", ".idea", ".settings"}
BINARY_SUFFIXES = {
    ".class", ".jar", ".war", ".ear", ".zip", ".gz", ".tar", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".pdf", ".xls", ".xlsx", ".doc", ".docx", ".ppt", ".pptx",
    ".so", ".dll", ".dylib", ".exe", ".woff", ".woff2", ".ttf", ".eot",
}

# 확장자 → 뷰어 하이라이트 언어
SOURCE_LANGS = {
    ".java": "java", ".xml": "xml", ".sql": "sql", ".properties": "properties",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".js": "js", ".ts": "js",
    ".jsp": "xml", ".html": "xml", ".htm": "xml", ".css": "css", ".md": "markdown",
}

# 프로젝트별 캐시 (index.json mtime 이 바뀌면 자동 재로딩)
_index_cache: dict[str, tuple[float, Any]] = {}
_stores: dict[str, DocStore] = {}
_cache_lock = threading.Lock()


def _lang(lang: str | None) -> str:
    return normalize(lang, cfg.language)


def resolve(project_id: str | None) -> tuple[Project, Config]:
    project = registry.get(project_id)
    return project, registry.config_for(project)


def store_of(project: Project) -> DocStore:
    with _cache_lock:
        store = _stores.get(project.id)
        if store is None or str(store.docs_dir) != project.docs_dir:
            store = DocStore(docs_dir=Path(project.docs_dir))
            _stores[project.id] = store
        return store


def index_of(project: Project, pcfg: Config, lang: str = "ko"):
    if not pcfg.index_file.exists():
        raise HTTPException(503, msg("no_index", lang))
    mtime = pcfg.index_file.stat().st_mtime
    with _cache_lock:
        cached = _index_cache.get(project.id)
        if cached and cached[0] == mtime:
            return cached[1]
    idx = load_index(pcfg, with_source=False)
    with _cache_lock:
        _index_cache[project.id] = (mtime, idx)
    return idx


def invalidate(project_id: str) -> None:
    with _cache_lock:
        _index_cache.pop(project_id, None)
        _stores.pop(project_id, None)


# --------------------------------------------------------------------------- #
# 프로젝트
# --------------------------------------------------------------------------- #
@app.get("/api/projects")
def list_projects():
    out = []
    for p in registry.all():
        pcfg = registry.config_for(p)
        out.append(
            {
                **p.to_dict(),
                "parsed": pcfg.index_file.exists(),
                "missing_roots": [r for r in p.roots if not Path(r).exists()],
            }
        )
    return {"projects": out, "active": registry.active_id()}


@app.post("/api/projects")
def add_project(payload: dict = Body(...)):
    """로컬 폴더를 새 프로젝트로 등록하고 곧바로 파싱을 시작한다."""
    raw = (payload.get("path") or "").strip()
    if not raw:
        raise HTTPException(400, "폴더 경로가 필요합니다.")
    path = Path(os.path.expanduser(raw)).resolve()
    if not path.is_dir():
        raise HTTPException(404, f"폴더를 찾을 수 없습니다: {path}")
    if not any(path == r or path.is_relative_to(r) for r in cfg.browse_roots):
        allowed = ", ".join(str(r) for r in cfg.browse_roots)
        raise HTTPException(403, f"열람이 허용된 경로 밖입니다. 허용: {allowed}")

    project = registry.add(path, payload.get("name") or None)
    registry.set_active(project.id)
    return {"project": project.to_dict(), "job": _start_parse(project)}


@app.post("/api/projects/upload")
def upload_project(
    files: list[UploadFile] = File(...),
    paths: list[str] = Form(default=[]),
    name: str = Form(default=""),
):
    """브라우저에서 올린 폴더(또는 ZIP)를 새 프로젝트로 등록하고 파싱한다.

    sync 로 둔다 — FastAPI 가 스레드풀에서 돌려 주므로 수천 개 파일을 쓰는
    동안 이벤트 루프가 멈추지 않고, UploadFile.file 을 그대로 스트리밍할 수
    있어 전체를 메모리에 올리지 않아도 된다.
    """
    if not files:
        raise HTTPException(400, "업로드된 파일이 없습니다.")

    root = cfg.upload_dir
    root.mkdir(parents=True, exist_ok=True)

    single_zip = len(files) == 1 and (files[0].filename or "").lower().endswith(".zip")
    label = (
        name.strip()
        or (Path(files[0].filename or "").stem if single_zip else "")
        # 폴더 업로드는 상대경로의 첫 마디가 곧 폴더 이름이다
        or (paths[0].replace("\\", "/").split("/")[0] if paths else "")
        or "upload"
    )
    dest = unique_dir(root, label)

    try:
        if single_zip:
            stats = extract_zip(dest, files[0].file)
        else:
            # paths 가 없거나 짧으면 그 자리는 파일명으로 채운다.
            # (webkitdirectory 를 못 쓰는 브라우저에서 낱개 파일만 올린 경우)
            items = [
                Incoming(
                    rel=(paths[i] if i < len(paths) and paths[i] else (f.filename or "")),
                    stream=f.file,
                )
                for i, f in enumerate(files)
            ]
            stats = store_files(dest, items)
    except UploadError as exc:
        discard(dest, root)
        raise HTTPException(400, str(exc)) from exc
    except Exception:
        discard(dest, root)
        raise

    project = registry.add(dest, label)
    registry.set_active(project.id)
    return {
        "project": project.to_dict(),
        "upload": stats.as_dict(),
        "job": _start_parse(project),
    }


@app.post("/api/projects/{project_id}/parse")
def reparse(project_id: str):
    project = registry.get(project_id)
    return {"project": project.to_dict(), "job": _start_parse(project)}


@app.post("/api/projects/{project_id}/activate")
def activate(project_id: str):
    project = registry.get(project_id)
    registry.set_active(project.id)
    return {"active": project.id}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str, purge: bool = True):
    if project_id == DEFAULT_ID:
        raise HTTPException(400, "config.yaml 의 기본 프로젝트는 삭제할 수 없습니다.")
    project = registry.get(project_id)
    if project.id != project_id:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    workspace = cfg.workspace_dir / project_id
    roots = [Path(r) for r in project.roots]
    removed = registry.remove(project_id)
    invalidate(project_id)
    # 사용자의 원본 폴더는 절대 건드리지 않는다. 지우는 것은 우리가 만든 것뿐 —
    # 산출물과, 브라우저 업로드로 uploads/ 에 풀어 둔 사본이다. (업로드 원본은
    # 사용자 PC 에 그대로 있으므로 여기 사본을 남기면 디스크만 쌓인다.)
    if removed and purge:
        if workspace.is_dir() and workspace.is_relative_to(cfg.workspace_dir):
            shutil.rmtree(workspace, ignore_errors=True)
        for root in roots:
            discard(root, cfg.upload_dir)
    return {"removed": removed}


def _start_parse(project: Project) -> str:
    pcfg = registry.config_for(project)

    def work(progress):
        progress(f"{project.name} 스캔 중…")
        idx = scan(pcfg)
        save_index(pcfg, idx)
        invalidate(project.id)
        counts = {
            "programs": len(idx.programs),
            "classes": len(idx.classes),
            "statements": len(idx.statements),
            "tables": len(idx.tables),
        }
        # 아무것도 못 찾았으면 '대신 무엇이 있었는지'를 남긴다. 이게 없으면
        # 화면에는 빈 목록만 남아 분석이 돌긴 한 건지 알 수 없다.
        found = None
        if not idx.classes:
            progress("Java 소스를 찾지 못했습니다 — 폴더 구성 확인 중…")
            found = survey(pcfg.source_roots)
        registry.update(
            project.id,
            parsed_at=datetime.now().isoformat(timespec="seconds"),
            counts=counts,
            survey=found,
        )
        return {"project": project.id, "counts": counts, "survey": found}

    return jobs.run("parse", work, project=project.id)


# --------------------------------------------------------------------------- #
# 산출물 생성
# --------------------------------------------------------------------------- #
@app.get("/api/providers")
def providers():
    """고를 수 있는 LLM 공급자와 각각의 준비 상태.

    외부 API(Grok/Claude)와 사내 GPU(Ollama)를 화면에서 바꿔 가며 쓰기 위한
    목록이다. 금융·공공 소스는 사내 모델로 돌려야 하는데, 그때마다
    config.yaml 을 고치고 서비스를 재시작할 수는 없다.
    """
    out = []
    for name in cfg.providers:
        pcfg = cfg.with_provider(name)
        opts = pcfg.llm_options
        out.append(
            {
                "id": name,
                "model": opts.get("model", ""),
                "local": name == "ollama",
                "ready": check_provider(name, opts).to_dict(),
            }
        )
    return {"providers": out, "default": cfg.provider}


@app.post("/api/generate")
def generate(payload: dict = Body(default={}), project: str | None = None):
    """LLM 으로 명세서를 만든다. doc_id 를 주면 그 프로그램만."""
    proj, pcfg = resolve(project or payload.get("project"))
    doc_id = payload.get("doc_id")
    force = bool(payload.get("force", True))

    # 뷰어에서 고른 공급자로 이번 생성만 돌린다.
    picked = (payload.get("provider") or "").strip()
    if picked:
        if picked not in cfg.providers:
            raise HTTPException(
                400, f"설정에 없는 공급자입니다: {picked} (가능: {', '.join(cfg.providers)})"
            )
        pcfg = pcfg.with_provider(picked)

    # 공급자가 준비 안 됐으면 스레드를 띄우기 전에 막는다. 그래야 SDK 원문이
    # 아니라 '무엇을 어떻게 고치라'는 메시지가 화면에 뜬다.
    ready = check_provider(pcfg.provider, pcfg.llm_options)
    if not ready.ok:
        raise HTTPException(400, f"{ready.reason}\n\n{ready.hint}")

    def work(progress):
        progress("인덱스 로딩 중…")
        idx = load_index(pcfg)
        done: list[str] = []

        def on_progress(pid: str, status: str) -> None:
            done.append(pid)
            progress(f"{status}: {pid} ({len(done)})")

        result = generate_all(
            pcfg, idx, only=doc_id, force=force, on_progress=on_progress
        )
        invalidate(proj.id)
        # generate_all 은 프로그램별 실패를 예외가 아니라 결과에 담는다.
        # 그대로 두면 아무것도 안 만들어졌는데 '완료'로 보인다.
        if result["failed"] and not result["generated"]:
            first = result["failed"][0]
            raise RuntimeError(f"{first['id']}: {first['error']}")
        if result["failed"]:
            result["warning"] = (
                f"{len(result['failed'])}건 실패: "
                + ", ".join(f["id"] for f in result["failed"][:5])
            )
        return result

    return {
        "job": jobs.run(
            "generate", work, project=proj.id, doc_id=doc_id, provider=pcfg.provider
        )
    }


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job


# --------------------------------------------------------------------------- #
# 로컬 폴더 탐색기
# --------------------------------------------------------------------------- #
@app.get("/api/fs/list")
def fs_list(path: str | None = None):
    """새 프로젝트로 열 폴더를 고르기 위한 디렉터리 목록.

    server.browse_roots(기본: 홈 디렉터리) 밖으로는 나가지 못한다.
    """
    roots = cfg.browse_roots
    target = Path(os.path.expanduser(path)).resolve() if path else roots[0]
    try:
        return {
            "roots": [str(r) for r in roots],
            "links": quick_links(roots),
            **list_dir(target, roots),
        }
    except PermissionError:
        raise HTTPException(403, "열람이 허용된 경로 밖입니다.")
    except FileNotFoundError:
        raise HTTPException(404, "폴더를 찾을 수 없습니다.")


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/meta")
def meta(project: str | None = None, lang: str | None = None):
    proj, pcfg = resolve(project)
    docs = store_of(proj).all()
    counts = {"programs": 0, "documents": len(docs), "classes": 0, "statements": 0, "tables": 0}
    parsed = pcfg.index_file.exists()
    if parsed:
        idx = index_of(proj, pcfg, _lang(lang))
        counts.update(
            programs=len(idx.programs),
            classes=len(idx.classes),
            statements=len(idx.statements),
            tables=len(idx.tables),
        )
    return {
        "project": pcfg.project_name,
        "project_id": proj.id,
        "parsed": parsed,
        "survey": proj.survey,
        "provider": cfg.provider,
        "provider_ready": check_provider(cfg.provider, cfg.llm_options).to_dict(),
        "language": cfg.language,
        "source_roots": [Path(r).name for r in proj.roots],
        "counts": counts,
    }


@app.get("/api/tree")
def tree(project: str | None = None, lang: str | None = None):
    proj, pcfg = resolve(project)
    if not pcfg.index_file.exists():
        return []
    idx = index_of(proj, pcfg, _lang(lang))
    have_doc = {d.id for d in store_of(proj).all()}
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for p in idx.programs:
        grouped[p.layer][p.tier].append(
            {
                "id": p.id,
                "name": p.name,
                "urls": p.urls,
                "tables": p.tables,
                "sql_count": len(p.sql_ids),
                "has_doc": p.id in have_doc,
            }
        )
    return [
        {
            "layer": layer,
            "tiers": [
                {"tier": tier, "programs": sorted(progs, key=lambda x: x["name"])}
                for tier, progs in sorted(tiers.items())
            ],
        }
        for layer, tiers in sorted(grouped.items())
    ]


@app.get("/api/doc/{doc_id}")
def doc(doc_id: str, project: str | None = None, lang: str | None = None):
    lg = _lang(lang)
    proj, pcfg = resolve(project)
    d = store_of(proj).get(doc_id)
    if not d:
        idx = index_of(proj, pcfg, lg)
        prog = next((p for p in idx.programs if p.id == doc_id), None)
        if prog:
            raise HTTPException(
                404, msg("doc_not_generated", lg, name=prog.name, id=doc_id)
            )
        raise HTTPException(404, msg("doc_not_found", lg))
    return {"id": d.id, "meta": d.meta, "markdown": d.body}


@app.get("/api/program/{doc_id}")
def program(doc_id: str, project: str | None = None, lang: str | None = None):
    """문서가 없어도 파서가 아는 사실은 보여 준다 (생성 전 미리보기용)."""
    lg = _lang(lang)
    proj, pcfg = resolve(project)
    idx = index_of(proj, pcfg, lg)
    prog = next((p for p in idx.programs if p.id == doc_id), None)
    if not prog:
        raise HTTPException(404, msg("program_not_found", lg))
    return {
        "id": prog.id,
        "name": prog.name,
        "layer": prog.layer,
        "entry": prog.entry_fqn,
        "urls": prog.urls,
        "tables": prog.tables,
        "classes": prog.classes,
        "files": prog.files,
        "sql_count": len(prog.sql_ids),
    }


@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1), limit: int = 40, project: str | None = None
):
    proj, _ = resolve(project)
    return {"query": q, "results": run_search(store_of(proj), q, limit)}


@app.get("/api/graph/{doc_id}")
def graph(doc_id: str, project: str | None = None, lang: str | None = None):
    lg = _lang(lang)
    proj, pcfg = resolve(project)
    idx = index_of(proj, pcfg, lg)
    prog = next((p for p in idx.programs if p.id == doc_id), None)
    if not prog:
        raise HTTPException(404, msg("program_not_found", lg))

    members = set(prog.classes)
    nodes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, str]] = []

    def add_node(key: str, label: str, kind: str) -> None:
        nodes.setdefault(key, {"id": key, "label": label, "kind": kind})

    for src, dst, kind in idx.edges:
        src_cls = src.split("#")[0]
        if src_cls not in members:
            continue
        if kind == "sql":
            if dst not in prog.sql_ids:
                continue
            add_node(src, src.split(".")[-1], idx.classes[src_cls].kind if src_cls in idx.classes else "unknown")
            add_node(dst, dst.split(".")[-1], "sql")
            links.append({"source": src, "target": dst, "kind": "sql"})
        else:
            dst_cls = dst.split("#")[0]
            if dst_cls not in members:
                continue
            add_node(src, src.split(".")[-1], idx.classes[src_cls].kind)
            add_node(dst, dst.split(".")[-1], idx.classes[dst_cls].kind)
            links.append({"source": src, "target": dst, "kind": "call"})

    for table in prog.tables:
        add_node(f"table:{table}", table, "table")
    for sid in prog.sql_ids:
        st = idx.statements.get(sid)
        if not st:
            continue
        add_node(sid, sid.split(".")[-1], "sql")
        for t, op in st.crud:
            links.append({"source": sid, "target": f"table:{t}", "kind": op})

    return {"nodes": list(nodes.values()), "links": links}


@app.get("/api/impact/{doc_id}")
def impact(doc_id: str, project: str | None = None, lang: str | None = None):
    proj, pcfg = resolve(project)
    return impact_of(index_of(proj, pcfg, _lang(lang)), doc_id)


@app.get("/api/tables")
def tables(project: str | None = None, lang: str | None = None):
    proj, pcfg = resolve(project)
    if not pcfg.index_file.exists():
        return []
    idx = index_of(proj, pcfg, _lang(lang))
    return [
        {
            "name": name,
            "crud": info.get("crud", []),
            "programs": info.get("programs", []),
            "statements": info.get("statements", []),
        }
        for name, info in sorted(idx.tables.items())
    ]


@app.get("/api/table/{name}")
def table_detail(name: str, project: str | None = None, lang: str | None = None):
    lg = _lang(lang)
    proj, pcfg = resolve(project)
    idx = index_of(proj, pcfg, lg)
    info = idx.tables.get(name.upper())
    if not info:
        raise HTTPException(404, msg("table_not_found", lg))
    by_id = {p.id: p for p in idx.programs}
    return {
        "name": name.upper(),
        "crud": info.get("crud", []),
        "programs": [
            {"id": pid, "name": by_id[pid].name, "layer": by_id[pid].layer}
            for pid in info.get("programs", [])
            if pid in by_id
        ],
        "statements": [
            {
                "id": sid,
                "kind": idx.statements[sid].kind,
                "path": idx.statements[sid].path,
                "sql": idx.statements[sid].sql,
            }
            for sid in info.get("statements", [])
            if sid in idx.statements
        ],
    }


# --------------------------------------------------------------------------- #
# 소스 브라우저
# --------------------------------------------------------------------------- #
@app.get("/api/source/tree")
def source_tree(project: str | None = None):
    """source_roots 아래 열람 가능한 파일 목록.

    뷰어가 이걸로 트리를 구성한다. 파싱 대상(.java/.xml)에는 parsed=true 를 달아
    '분석에 쓰인 파일'과 '그냥 딸려 있는 파일'을 구분할 수 있게 한다.
    """
    _, pcfg = resolve(project)
    roots: list[dict[str, Any]] = []
    for i, root in enumerate(pcfg.source_roots):
        files: list[dict[str, Any]] = []
        truncated = False
        if root.exists():
            # os.walk + 가지치기. rglob 은 .venv / node_modules 안까지 다 내려가
            # 임의의 로컬 폴더를 열었을 때 응답이 수십 초로 뛴다.
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(
                    d
                    for d in dirnames
                    if d not in SKIP_DIRS and d not in HIDDEN_DIRS and not d.startswith(".")
                )
                if len(files) >= MAX_TREE_FILES:
                    truncated = True
                    break
                for name in sorted(filenames):
                    if len(files) >= MAX_TREE_FILES:
                        truncated = True
                        break
                    suffix = Path(name).suffix.lower()
                    if name.startswith(".") or suffix in BINARY_SUFFIXES:
                        continue
                    path = Path(dirpath) / name
                    if path.is_symlink():
                        continue
                    rel = str(path.relative_to(root)).replace("\\", "/")
                    if _excluded(rel, pcfg.exclude):
                        continue
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    files.append(
                        {
                            "path": rel,
                            "size": size,
                            "lang": SOURCE_LANGS.get(suffix, "text"),
                            "parsed": suffix in (".java", ".xml"),
                        }
                    )
        roots.append(
            {
                "index": i,
                "name": root.name or str(root),
                "path": str(root),
                "files": files,
                "truncated": truncated,
            }
        )
    return roots


@app.get("/api/source")
def source(
    path: str, root: int | None = None, project: str | None = None, lang: str | None = None
):
    """원본 소스 열람 (source_roots 밖은 차단)."""
    lg = _lang(lang)
    _, pcfg = resolve(project)
    source_roots = pcfg.source_roots
    candidates = (
        [source_roots[root]]
        if root is not None and 0 <= root < len(source_roots)
        else source_roots
    )
    for base in candidates:
        target = (base / path).resolve()
        # is_relative_to 로 확인한다. 문자열 startswith 는 /srv/src 와 /srv/src-old 를
        # 구분하지 못해 루트 밖 파일이 새어 나갈 수 있다.
        if not target.is_relative_to(base) or not target.is_file():
            continue
        size = target.stat().st_size
        if size > MAX_SOURCE_BYTES:
            raise HTTPException(
                413, msg("source_too_large", lg, size=size, limit=MAX_SOURCE_BYTES)
            )
        content = _read(target)
        if content is None:
            raise HTTPException(415, msg("source_binary", lg))
        return {
            "path": path,
            "root": source_roots.index(base),
            "lang": SOURCE_LANGS.get(target.suffix.lower(), "text"),
            "lines": content.count("\n") + 1,
            "content": content,
        }
    raise HTTPException(404, msg("source_not_found", lg))


@app.get("/api/export/{doc_id}.xlsx")
def export_excel(doc_id: str, project: str | None = None, lang: str | None = None):
    lg = _lang(lang)
    proj, pcfg = resolve(project)
    d = store_of(proj).get(doc_id)
    if not d:
        raise HTTPException(404, msg("doc_not_found", lg))
    idx = index_of(proj, pcfg, lg)
    statements = [
        {
            "full_id": sid,
            "kind": idx.statements[sid].kind,
            "params": idx.statements[sid].params,
            "path": idx.statements[sid].path,
            "line": idx.statements[sid].line,
            "sql": idx.statements[sid].sql,
        }
        for sid in (d.meta.get("sql_ids") or [])
        if sid in idx.statements
    ]
    # 시트·헤더는 문서가 생성된 언어를 따른다 (본문과 어긋나지 않도록).
    doc_lang = normalize(d.meta.get("language"), lg)
    data = build_workbook(d.meta, d.body, impact_of(idx, doc_id), statements, doc_lang)
    suffix = "_명세서" if doc_lang == "ko" else "_spec"
    filename = safe_filename(f"{d.meta.get('name', doc_id)}{suffix}.xlsx")
    quoted = urllib.parse.quote(filename)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


def _excluded(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch("/" + rel, p) for p in patterns)


def _read(path: Path) -> str | None:
    """레거시 소스는 EUC-KR 이 흔하다. 바이너리면 None."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    for encoding in ("utf-8", "euc-kr"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# 정적 파일 (빌드된 뷰어)
# --------------------------------------------------------------------------- #
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"

if WEB_DIST.exists():

    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = (WEB_DIST / full_path).resolve()
        if full_path and candidate.is_relative_to(WEB_DIST) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")

else:

    @app.get("/")
    def not_built():
        return Response(
            f"<h1>{msg('not_built', cfg.language)}</h1>"
            "<p><code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code></p>"
            "<p>API: <a href='/docs'>/docs</a></p>",
            media_type="text/html",
        )
