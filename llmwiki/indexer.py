"""소스 스캔 → 정적 분석 → index.json 저장/로드."""

from __future__ import annotations

import fnmatch
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .models import JavaClass, JavaMethod, MapperXml, Program, SqlStatement, to_dict
from .parsers.graph import Index, build_index
from .parsers.java import parse_java_file
from .parsers.mybatis import parse_mapper_xml


def scan(cfg: Config) -> Index:
    classes: list[JavaClass] = []
    mappers: list[MapperXml] = []

    for root in cfg.source_roots:
        if not root.exists():
            raise FileNotFoundError(f"소스 경로가 없습니다: {root}")
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            if _excluded(rel, cfg.exclude):
                continue
            if path.suffix == ".java":
                classes.extend(parse_java_file(path, root))
            elif path.suffix == ".xml":
                mapper = parse_mapper_xml(path, root)
                if mapper:
                    mappers.append(mapper)

    return build_index(cfg.project_name, classes, mappers, cfg.layers)


def _excluded(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch("/" + rel, p) for p in patterns)


def save_index(cfg: Config, idx: Index) -> Path:
    cfg.index_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "project": idx.project,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "classes": {k: _class_dict(v) for k, v in idx.classes.items()},
        "mappers": {k: to_dict(v) for k, v in idx.mappers.items()},
        "statements": {k: to_dict(v) for k, v in idx.statements.items()},
        "programs": [to_dict(p) for p in idx.programs],
        "edges": idx.edges,
        "tables": idx.tables,
    }
    cfg.index_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cfg.index_file


def _class_dict(cls: JavaClass) -> dict[str, Any]:
    d = to_dict(cls)
    # 원본 전체를 index.json 에 넣으면 파일이 비대해진다 — 문서 생성 시 다시 읽는다
    d.pop("source", None)
    for m in d.get("methods", []):
        m.pop("body", None)
    return d


def load_index(cfg: Config, *, with_source: bool = True) -> Index:
    """저장된 index.json 을 읽는다. 문서 생성용으로는 원본 소스를 다시 로드한다."""
    if not cfg.index_file.exists():
        raise FileNotFoundError(
            f"인덱스가 없습니다: {cfg.index_file}\n먼저 `llmwiki parse` 를 실행하세요."
        )
    data = json.loads(cfg.index_file.read_text(encoding="utf-8"))

    idx = Index(project=data.get("project", cfg.project_name))
    idx.edges = data.get("edges", [])
    idx.tables = data.get("tables", {})

    for fqn, raw in data.get("classes", {}).items():
        methods = [JavaMethod(**m) for m in raw.pop("methods", [])]
        cls = JavaClass(**raw, methods=methods)
        idx.classes[fqn] = cls

    for ns, raw in data.get("mappers", {}).items():
        stmts = [SqlStatement(**s) for s in raw.pop("statements", [])]
        idx.mappers[ns] = MapperXml(**raw, statements=stmts)

    for sid, raw in data.get("statements", {}).items():
        idx.statements[sid] = SqlStatement(**raw)

    idx.programs = [Program(**p) for p in data.get("programs", [])]

    if with_source:
        _reload_sources(cfg, idx)
    return idx


def _reload_sources(cfg: Config, idx: Index) -> None:
    roots = cfg.source_roots
    for cls in idx.classes.values():
        for root in roots:
            p = root / cls.path
            if p.exists():
                try:
                    cls.source = p.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    cls.source = p.read_text(encoding="euc-kr", errors="replace")
                break
