"""설정 로딩."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")


@dataclass
class Config:
    raw: dict[str, Any]
    root: Path

    # --- project ---
    @property
    def project_name(self) -> str:
        return self.raw.get("project", {}).get("name", "LLMWiki")

    @property
    def source_roots(self) -> list[Path]:
        roots = self.raw.get("project", {}).get("source_roots", ["./src"])
        return [(self.root / r).resolve() for r in roots]

    @property
    def layers(self) -> list[dict[str, str]]:
        return self.raw.get("project", {}).get("layers", [])

    # --- parse ---
    @property
    def include(self) -> list[str]:
        return self.raw.get("parse", {}).get("include", ["**/*.java", "**/*.xml"])

    @property
    def exclude(self) -> list[str]:
        return self.raw.get("parse", {}).get("exclude", [])

    @property
    def max_class_chars(self) -> int:
        return int(self.raw.get("parse", {}).get("max_class_chars", 12000))

    # --- llm ---
    @property
    def provider(self) -> str:
        return os.environ.get("LLMWIKI_PROVIDER") or self.raw.get("llm", {}).get(
            "provider", "claude"
        )

    @property
    def llm_options(self) -> dict[str, Any]:
        return self.raw.get("llm", {}).get(self.provider, {})

    @property
    def concurrency(self) -> int:
        return int(self.llm_options.get("concurrency", 2))

    # --- output ---
    @property
    def docs_dir(self) -> Path:
        return (self.root / self.raw.get("output", {}).get("docs_dir", "./docs")).resolve()

    @property
    def index_file(self) -> Path:
        return (
            self.root / self.raw.get("output", {}).get("index_file", "./docs/index.json")
        ).resolve()

    @property
    def language(self) -> str:
        """산출물·UI 기본 언어. ko | en (환경변수 LLMWIKI_LANG 로 덮어쓰기)."""
        value = os.environ.get("LLMWIKI_LANG") or self.raw.get("output", {}).get(
            "language", "ko"
        )
        return value if value in ("ko", "en") else "ko"

    # --- server ---
    @property
    def host(self) -> str:
        return self.raw.get("server", {}).get("host", "127.0.0.1")

    @property
    def port(self) -> int:
        return int(self.raw.get("server", {}).get("port", 8722))


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    p = p.resolve()
    if not p.exists():
        raise FileNotFoundError(f"설정 파일이 없습니다: {p}")
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config(raw=raw, root=p.parent)
