"""로컬 폴더 불러오기 · 프로젝트 전환 회귀 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwiki.config import load_config
from llmwiki.indexer import scan
from llmwiki.workspace import DEFAULT_ID, Registry, list_dir, probe

ROOT = Path(__file__).resolve().parents[1]

SAMPLE_CONTROLLER = """
package com.acme.web;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.RequestMapping;

@Controller
@RequestMapping("/acme")
public class AcmeController {
    @RequestMapping("/list.do")
    public String list() { return "acme/list"; }
}
"""


@pytest.fixture
def workspace(tmp_path: Path) -> tuple[Registry, Path]:
    """config.yaml 을 tmp 로 복사해 실제 레지스트리를 건드리지 않는다."""
    cfg = load_config(ROOT / "config.yaml")
    cfg.raw["output"]["workspace_dir"] = str(tmp_path / "projects")
    cfg.root = tmp_path
    cfg.raw["project"]["source_roots"] = [str(ROOT / "sample")]
    cfg.raw["output"]["docs_dir"] = str(ROOT / "docs")
    cfg.raw["output"]["index_file"] = str(ROOT / "docs/index.json")
    return Registry(cfg), tmp_path


def test_builtin_project_always_present(workspace):
    registry, _ = workspace
    projects = registry.all()
    assert projects[0].id == DEFAULT_ID
    assert projects[0].builtin is True
    assert registry.active_id() == DEFAULT_ID


def test_add_project_isolates_output(workspace, tmp_path):
    registry, ws = workspace
    src = tmp_path / "acme"
    src.mkdir()
    project = registry.add(src, "Acme")

    assert project.id == "acme"
    # 산출물은 프로젝트별로 갈라져야 기본 프로젝트의 docs 를 덮지 않는다
    assert Path(project.docs_dir) != Path(registry.cfg.docs_dir)
    assert Path(project.index_file).parent == ws / "projects" / "acme"
    assert registry.active_id() == "acme"


def test_add_same_folder_twice_reuses_entry(workspace, tmp_path):
    registry, _ = workspace
    src = tmp_path / "acme"
    src.mkdir()
    first = registry.add(src, "Acme")
    second = registry.add(src, "Acme again")
    assert first.id == second.id
    assert len(registry.all()) == 2  # default + acme


def test_id_collision_gets_suffix(workspace, tmp_path):
    registry, _ = workspace
    (tmp_path / "a" / "acme").mkdir(parents=True)
    (tmp_path / "b" / "acme").mkdir(parents=True)
    first = registry.add(tmp_path / "a" / "acme")
    second = registry.add(tmp_path / "b" / "acme")
    assert first.id == "acme"
    assert second.id == "acme-2"


def test_remove_keeps_builtin(workspace, tmp_path):
    registry, _ = workspace
    src = tmp_path / "acme"
    src.mkdir()
    registry.add(src)
    assert registry.remove(DEFAULT_ID) is False
    assert registry.remove("acme") is True
    assert [p.id for p in registry.all()] == [DEFAULT_ID]
    assert registry.active_id() == DEFAULT_ID


def test_derived_config_parses_the_new_folder(workspace, tmp_path):
    """불러온 폴더가 실제로 파싱돼 프로그램이 나와야 한다."""
    registry, _ = workspace
    src = tmp_path / "acme" / "src" / "main" / "java" / "com" / "acme" / "web"
    src.mkdir(parents=True)
    (src / "AcmeController.java").write_text(SAMPLE_CONTROLLER, encoding="utf-8")

    project = registry.add(tmp_path / "acme")
    pcfg = registry.config_for(project)
    idx = scan(pcfg)

    assert [p.entry_fqn for p in idx.programs] == ["com.acme.web.AcmeController"]
    assert idx.programs[0].urls == ["/acme/list.do"]


def test_registry_file_is_json(workspace, tmp_path):
    registry, ws = workspace
    (tmp_path / "acme").mkdir()
    registry.add(tmp_path / "acme")
    data = json.loads((ws / "projects" / "projects.json").read_text(encoding="utf-8"))
    assert data["active"] == "acme"
    assert [p["id"] for p in data["projects"]] == ["acme"]


# --------------------------------------------------------------------------- #
# 폴더 탐색기
# --------------------------------------------------------------------------- #
def test_list_dir_stays_inside_roots(tmp_path):
    (tmp_path / "inside").mkdir()
    with pytest.raises(PermissionError):
        list_dir(tmp_path.parent, [tmp_path])


def test_list_dir_hides_noise(tmp_path):
    for name in ("src", ".git", "node_modules", "target", ".venv"):
        (tmp_path / name).mkdir()
    listing = list_dir(tmp_path, [tmp_path])
    assert [e["name"] for e in listing["entries"]] == ["src"]
    assert listing["parent"] is None  # 루트 위로는 못 올라간다


def test_probe_counts_and_prunes(tmp_path):
    deep = tmp_path / "src" / "main" / "java"
    deep.mkdir(parents=True)
    (deep / "A.java").write_text("class A {}", encoding="utf-8")
    (deep / "B.java").write_text("class B {}", encoding="utf-8")
    (tmp_path / "m.xml").write_text("<x/>", encoding="utf-8")

    noise = tmp_path / "node_modules" / "pkg"
    noise.mkdir(parents=True)
    (noise / "C.java").write_text("class C {}", encoding="utf-8")

    counts = probe(tmp_path)
    assert counts["java"] == 2 and counts["xml"] == 1
    assert counts["capped"] == 0
    assert counts["has_dirs"] is True


def test_probe_reports_cap(tmp_path):
    for i in range(30):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    assert probe(tmp_path, cap=10)["capped"] == 1


def test_probe_detects_project_markers(tmp_path):
    """pom.xml / .git 같은 표식은 최상위에서만 인정한다 — 하위까지 세면 온통 배지가 된다."""
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "sub"
    nested.mkdir()
    (nested / "build.gradle").write_text("", encoding="utf-8")

    assert probe(tmp_path)["markers"] == ["git", "maven"]
    assert probe(nested)["markers"] == ["gradle"]


def test_probe_has_dirs_is_top_level_only(tmp_path):
    (tmp_path / "a.java").write_text("class A {}", encoding="utf-8")
    assert probe(tmp_path)["has_dirs"] is False
    (tmp_path / "sub").mkdir()
    assert probe(tmp_path)["has_dirs"] is True


def test_list_dir_gives_crumbs_from_root(tmp_path):
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    listing = list_dir(deep, [tmp_path])
    assert [c["label"] for c in listing["crumbs"]] == [tmp_path.name, "a", "b"]
    assert listing["crumbs"][0]["path"] == str(tmp_path)
    assert listing["parent"] == str(tmp_path / "a")


def test_scan_skips_dependency_dirs(tmp_path):
    """node_modules/.venv 가 섞인 임의 폴더를 불러와도 헤매지 않아야 한다."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "AcmeController.java").write_text(SAMPLE_CONTROLLER, encoding="utf-8")
    junk = tmp_path / "node_modules" / "dep"
    junk.mkdir(parents=True)
    (junk / "Fake.java").write_text("@Controller public class Fake {}", encoding="utf-8")

    cfg = load_config(ROOT / "config.yaml").derive(
        name="tmp",
        source_roots=[str(tmp_path)],
        docs_dir=str(tmp_path / "docs"),
        index_file=str(tmp_path / "index.json"),
    )
    idx = scan(cfg)
    assert list(idx.classes) == ["com.acme.web.AcmeController"]


# --------------------------------------------------------------------------- #
# survey — 분석 결과가 0건일 때 '무엇이 있었는지'
# --------------------------------------------------------------------------- #
def test_survey_reports_what_was_there(tmp_path):
    """Java 가 없을 때 화면이 빈 목록만 보여 주지 않도록, 대신 무엇이 있었는지 남긴다."""
    from llmwiki.workspace import survey

    (tmp_path / "src").mkdir()
    for i in range(3):
        (tmp_path / "src" / f"c{i}.tsx").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / ".hidden").write_text("x", encoding="utf-8")
    junk = tmp_path / "node_modules" / "dep"
    junk.mkdir(parents=True)
    (junk / "index.js").write_text("x", encoding="utf-8")

    result = survey([tmp_path])
    assert result["files"] == 5  # .hidden 과 node_modules 는 빠진다
    assert result["by_ext"][0] == {"ext": ".tsx", "count": 3}
    assert "node_modules" in result["skipped_dirs"]
    assert result["capped"] is False


def test_survey_caps_on_huge_trees(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    assert survey_capped(tmp_path) is True


def survey_capped(path):
    from llmwiki.workspace import survey

    return survey([path], cap=5)["capped"]


def test_korean_name_gets_unique_id(workspace, tmp_path):
    """한글 이름은 슬러그가 비어 project 하나로 뭉개진다 — 경로 해시로 구분한다."""
    registry, _ = workspace
    a = tmp_path / "가"
    b = tmp_path / "나"
    a.mkdir()
    b.mkdir()
    first = registry.add(a, "고객관리")
    second = registry.add(b, "여신관리")
    assert first.id != second.id
    assert first.id not in ("project", "")
