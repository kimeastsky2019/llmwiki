"""설정 로딩."""

from __future__ import annotations

import copy
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
    # 요청 한 건만 다른 공급자로 돌리고 싶을 때 (뷰어의 공급자 선택).
    # config.yaml 도 환경변수도 건드리지 않으므로 서버 기본값은 그대로 남는다.
    provider_override: str | None = None

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
        return (
            self.provider_override
            or os.environ.get("LLMWIKI_PROVIDER")
            or self.raw.get("llm", {}).get("provider", "claude")
        )

    @property
    def providers(self) -> list[str]:
        """config.yaml 에 옵션이 적혀 있는 공급자들 (뷰어의 선택지).

        llm 아래에서 값이 dict 인 키만 센다. provider: 는 문자열이라 빠진다.
        현재 기본 공급자는 옵션 블록이 없어도 목록에 남긴다 — 고를 수 있는데
        지금 쓰는 것이 목록에 없으면 화면이 이상해진다.
        """
        llm = self.raw.get("llm", {})
        names = [k for k, v in llm.items() if isinstance(v, dict)]
        if self.provider not in names:
            names.insert(0, self.provider)
        return names

    def with_provider(self, name: str) -> "Config":
        """공급자만 바꾼 같은 설정. raw 는 읽기 전용으로만 쓰므로 공유한다."""
        return Config(raw=self.raw, root=self.root, provider_override=name)

    @property
    def llm_options(self) -> dict[str, Any]:
        """공급자 옵션. 환경변수로 덮어쓸 수 있다.

        config.yaml 이 사내 GPU 서버를 가리키는데 지금은 로컬에서 돌려 보고
        싶은 경우가 흔하다. 설정 파일을 고치지 않고 넘길 수 있어야 한다.
          LLMWIKI_OLLAMA_URL / LLMWIKI_OLLAMA_MODEL / LLMWIKI_MODEL
        """
        opts = dict(self.raw.get("llm", {}).get(self.provider, {}))
        if self.provider == "ollama":
            if url := os.environ.get("LLMWIKI_OLLAMA_URL"):
                opts["base_url"] = url
            if model := os.environ.get("LLMWIKI_OLLAMA_MODEL"):
                opts["model"] = model
        if self.provider == "grok":
            # 키와 같은 곳(.env)에서 모델도 같이 오도록 XAI_* 를 인정한다.
            if url := os.environ.get("XAI_BASE_URL"):
                opts["base_url"] = url
            if model := os.environ.get("XAI_MODEL"):
                opts["model"] = model
        if model := os.environ.get("LLMWIKI_MODEL"):
            opts["model"] = model
        return opts

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

    @property
    def workspace_dir(self) -> Path:
        """UI 로 불러온 프로젝트들이 저장되는 곳."""
        return (
            self.root / self.raw.get("output", {}).get("workspace_dir", "./projects")
        ).resolve()

    # --- server ---
    @property
    def host(self) -> str:
        return self.raw.get("server", {}).get("host", "127.0.0.1")

    @property
    def port(self) -> int:
        return int(self.raw.get("server", {}).get("port", 8722))

    @property
    def upload_dir(self) -> Path:
        """브라우저로 올린 소스가 풀리는 곳.

        docs/·projects/ 와 섞지 않는다 — 여기 있는 것은 우리가 만든 산출물이
        아니라 사용자 원본이라, 프로젝트를 지울 때 같이 지워지면 안 된다.
        """
        return (
            self.root / self.raw.get("server", {}).get("upload_dir", "./uploads")
        ).resolve()

    @property
    def browse_roots(self) -> list[Path]:
        """폴더 탐색기가 내려갈 수 있는 최상위. 기본은 홈 디렉터리 하나."""
        raw = self.raw.get("server", {}).get("browse_roots")
        if not raw:
            return [Path.home()]
        return [Path(os.path.expanduser(r)).resolve() for r in raw]

    # --- 프로젝트별 파생 ---
    def derive(
        self,
        *,
        name: str,
        source_roots: list[str],
        docs_dir: str,
        index_file: str,
        layers: list[dict[str, str]] | None = None,
    ) -> "Config":
        """같은 파싱·LLM 설정으로 다른 소스/산출물 경로를 보는 Config.

        scan/load_index/generate_all 이 전부 Config 하나만 받으므로,
        프로젝트 전환은 이 파생 객체를 넘기는 것으로 끝난다.
        """
        raw = copy.deepcopy(self.raw)
        raw.setdefault("project", {})
        raw["project"]["name"] = name
        raw["project"]["source_roots"] = source_roots
        raw["project"]["layers"] = layers if layers is not None else []
        raw.setdefault("output", {})
        raw["output"]["docs_dir"] = docs_dir
        raw["output"]["index_file"] = index_file
        # 경로는 이미 절대경로이므로 root 가 무엇이든 그대로 해석된다
        return Config(raw=raw, root=self.root, provider_override=self.provider_override)


def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    p = p.resolve()
    if not p.exists():
        raise FileNotFoundError(f"설정 파일이 없습니다: {p}")
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config(raw=raw, root=p.parent)
