"""소스 스캔 → 정적 분석 → index.json 저장/로드."""

from __future__ import annotations

import fnmatch
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import Config
from .workspace import SKIP_DIRS
from .models import JavaClass, JavaMethod, MapperXml, Program, SqlStatement, to_dict
from .parsers.graph import Index, build_index
from .parsers.java import parse_java_file
from .parsers.mybatis import parse_mapper_xml
from .parsers.pydata import model_tables, parse_python_data
from .parsers.python import parse_python_file


def scan(cfg: Config) -> Index:
    classes: list[JavaClass] = []
    mappers: list[MapperXml] = []

    for root in cfg.source_roots:
        if not root.exists():
            raise FileNotFoundError(f"소스 경로가 없습니다: {root}")
        files = _source_files(root, cfg.exclude)

        # 파이썬은 모델 정의와 사용처가 다른 모듈이라 모델을 먼저 전부 모은다.
        # 이 선행 수집이 없으면 db.add(customer) 의 대상 테이블을 알 수 없다.
        py_models: dict[str, str] = {}
        for path in files:
            if path.suffix == ".py":
                py_models.update(model_tables(path))

        for path in files:
            if path.suffix == ".java":
                classes.extend(parse_java_file(path, root))
            elif path.suffix == ".xml":
                mapper = parse_mapper_xml(path, root)
                if mapper:
                    mappers.append(mapper)
            elif path.suffix == ".py":
                classes.extend(parse_python_file(path, root))
                mapper = parse_python_data(path, root, py_models)
                if mapper:
                    mappers.append(mapper)

    return build_index(cfg.project_name, classes, mappers, cfg.layers)


SOURCE_SUFFIXES = (".java", ".xml", ".py")


def _source_files(root: Path, exclude: list[str]) -> list[Path]:
    """분석 대상 확장자만, 의존성·VCS·빌드 디렉터리는 들어가지도 않고 건너뛴다.

    rglob 로 전부 훑으면 임의의 로컬 폴더(node_modules, .venv, .git 가 섞인)를
    불러왔을 때 파일 수십만 개를 헤매게 된다. 가지치기가 있어야 쓸 수 있다.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")
        )
        for name in sorted(filenames):
            if not name.endswith(SOURCE_SUFFIXES):
                continue
            path = Path(dirpath) / name
            rel = str(path.relative_to(root)).replace("\\", "/")
            if _excluded(rel, exclude):
                continue
            found.append(path)
    return found


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
