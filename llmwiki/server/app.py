"""FastAPI 뷰어 서버."""

from __future__ import annotations

import fnmatch
import os
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from ..config import load_config
from ..i18n import msg, normalize
from ..indexer import load_index
from ..parsers.graph import impact_of
from .excel import build_workbook, safe_filename
from .search import DocStore, search as run_search

CONFIG_PATH = os.environ.get("LLMWIKI_CONFIG", "config.yaml")
cfg = load_config(CONFIG_PATH)
store = DocStore(docs_dir=cfg.docs_dir)

app = FastAPI(title=f"{cfg.project_name} — LLMWiki")

_index_cache: dict[str, Any] = {"mtime": None, "index": None}

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


def _lang(lang: str | None) -> str:
    return normalize(lang, cfg.language)


def get_index(lang: str = "ko"):
    """index.json 이 바뀌면 자동 재로딩."""
    if not cfg.index_file.exists():
        raise HTTPException(503, msg("no_index", lang))
    mtime = cfg.index_file.stat().st_mtime
    if _index_cache["mtime"] != mtime:
        _index_cache["index"] = load_index(cfg, with_source=False)
        _index_cache["mtime"] = mtime
    return _index_cache["index"]


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/meta")
def meta(lang: str | None = None):
    idx = get_index(_lang(lang))
    docs = store.all()
    return {
        "project": cfg.project_name,
        "provider": cfg.provider,
        "language": cfg.language,
        "source_roots": [r.name for r in cfg.source_roots],
        "counts": {
            "programs": len(idx.programs),
            "documents": len(docs),
            "classes": len(idx.classes),
            "statements": len(idx.statements),
            "tables": len(idx.tables),
        },
    }


@app.get("/api/tree")
def tree(lang: str | None = None):
    idx = get_index(_lang(lang))
    have_doc = {d.id for d in store.all()}
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
def doc(doc_id: str, lang: str | None = None):
    lg = _lang(lang)
    d = store.get(doc_id)
    if not d:
        idx = get_index(lg)
        prog = next((p for p in idx.programs if p.id == doc_id), None)
        if prog:
            raise HTTPException(
                404, msg("doc_not_generated", lg, name=prog.name, id=doc_id)
            )
        raise HTTPException(404, msg("doc_not_found", lg))
    return {"id": d.id, "meta": d.meta, "markdown": d.body}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = 40):
    return {"query": q, "results": run_search(store, q, limit)}


@app.get("/api/graph/{doc_id}")
def graph(doc_id: str, lang: str | None = None):
    lg = _lang(lang)
    idx = get_index(lg)
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
def impact(doc_id: str, lang: str | None = None):
    return impact_of(get_index(_lang(lang)), doc_id)


@app.get("/api/tables")
def tables(lang: str | None = None):
    idx = get_index(_lang(lang))
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
def table_detail(name: str, lang: str | None = None):
    lg = _lang(lang)
    idx = get_index(lg)
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
def source_tree():
    """source_roots 아래 열람 가능한 파일 목록.

    뷰어가 이걸로 트리를 구성한다. 파싱 대상(.java/.xml)에는 parsed=true 를 달아
    '분석에 쓰인 파일'과 '그냥 딸려 있는 파일'을 구분할 수 있게 한다.
    """
    roots: list[dict[str, Any]] = []
    for i, root in enumerate(cfg.source_roots):
        files: list[dict[str, Any]] = []
        if root.exists():
            for path in sorted(root.rglob("*")):
                if len(files) >= MAX_TREE_FILES:
                    break
                if not path.is_file() or path.is_symlink():
                    continue
                rel = str(path.relative_to(root)).replace("\\", "/")
                parts = rel.split("/")
                if any(p in HIDDEN_DIRS or p.startswith(".") for p in parts[:-1]):
                    continue
                if path.suffix.lower() in BINARY_SUFFIXES:
                    continue
                if _excluded(rel, cfg.exclude):
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                files.append(
                    {
                        "path": rel,
                        "size": size,
                        "lang": SOURCE_LANGS.get(path.suffix.lower(), "text"),
                        "parsed": path.suffix.lower() in (".java", ".xml"),
                    }
                )
        roots.append(
            {"index": i, "name": root.name or str(root), "path": str(root), "files": files}
        )
    return roots


@app.get("/api/source")
def source(path: str, root: int | None = None, lang: str | None = None):
    """원본 소스 열람 (source_roots 밖은 차단)."""
    lg = _lang(lang)
    candidates = (
        [cfg.source_roots[root]]
        if root is not None and 0 <= root < len(cfg.source_roots)
        else cfg.source_roots
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
            "root": cfg.source_roots.index(base),
            "lang": SOURCE_LANGS.get(target.suffix.lower(), "text"),
            "lines": content.count("\n") + 1,
            "content": content,
        }
    raise HTTPException(404, msg("source_not_found", lg))


@app.get("/api/export/{doc_id}.xlsx")
def export_excel(doc_id: str, lang: str | None = None):
    lg = _lang(lang)
    d = store.get(doc_id)
    if not d:
        raise HTTPException(404, msg("doc_not_found", lg))
    idx = get_index(lg)
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
