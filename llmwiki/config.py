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

    # --- compliance (규제 지식그래프) ---
    @property
    def compliance_dir(self) -> Path:
        """승인 저널·변경 제안·원문이 쌓이는 곳.

        docs/ 와 섞지 않는다 — 여기 있는 것은 재생성 가능한 산출물이 아니라
        감사 추적이라, 지우면 과거 판정의 근거가 사라진다.
        """
        return (
            self.root / self.raw.get("compliance", {}).get("dir", "./compliance")
        ).resolve()

    @property
    def ruleset_version(self) -> str:
        return str(self.raw.get("compliance", {}).get("ruleset", "1.0.0"))

    # --- kb (문서 지식베이스) ---
    @property
    def kb_dir(self) -> Path:
        """4채널로 분해해 적재한 문서와 적재 이력이 쌓이는 곳.

        docs/ 와 섞지 않는다 — 여기 있는 것은 다시 만들 수 있는 산출물이 아니라
        규제 게이트를 통과한 적재본과 그 이력이다. 지우면 무엇이 언제 어떤 판정으로
        들어왔는지가 사라진다.
        """
        return (self.root / self.raw.get("kb", {}).get("dir", "./knowledge")).resolve()

    @property
    def kb_destination(self) -> str:
        """문서 내용이 실제로 도달하는 곳을 판단할 기준 공급자.

        국외 이전 해당성(개인정보보호법 제28조의8)이 여기서 갈린다. 기본값은 지금
        쓰는 LLM 공급자다 — 사내 모델로 돌리는데 국외 이전 차단이 뜨거나, 더 나쁘게는
        외부로 보내면서 통과가 뜨는 것을 막는다.
        """
        return str(self.raw.get("kb", {}).get("destination", "") or self.provider)

    # --- wiki (에너지 진단 위키) ---
    @property
    def wiki_dir(self) -> Path:
        """마크다운 위키가 사는 곳. **이 저장소가 진실이다** (P1).

        docs/ 와 섞지 않는다 — docs/ 는 소스에서 매번 다시 만드는 산출물이고, 여기는
        사람이 검토하고 서명한 지식이다. 재생성하면 검토 이력이 사라진다.
        """
        return (self.root / self.raw.get("wiki", {}).get("dir", "./wiki")).resolve()

    @property
    def wiki_pipeline_version(self) -> str:
        """front-matter 의 provenance.pipeline_version 에 박히는 값.

        파이프라인을 고쳤는데 이 값을 안 올리면, 어떤 페이지가 어느 규칙으로 만들어졌는지
        구분할 수 없다.
        """
        return str(self.raw.get("wiki", {}).get("pipeline_version", "v0.1.0"))

    @property
    def wiki_owner(self) -> str:
        return str(self.raw.get("wiki", {}).get("owner", "energy-team"))

    @property
    def standard_version(self) -> str:
        return str(self.raw.get("compliance", {}).get("standard", ""))

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
