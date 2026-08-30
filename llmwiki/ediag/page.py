"""위키 페이지 한 장 — YAML front-matter + 마크다운 본문.

포맷을 마크다운 하나로 고정한 이유는 셋이다.

1. 진단 보고서의 섹션 구조(개요/현황/문제점/개선안/절감효과)와 그대로 맞물린다.
2. 위키 링크 `[[id]]` 로 설비·개선안·법규가 서로 참조되는 실제 지식 구조를 표현한다.
3. 사람이 편집기로 고칠 수 있다 — 검토자가 도구 없이 손댈 수 있어야 검토가 돈다.

파싱을 직접 한다. 프런트매터 라이브러리가 한글 값을 다루는 방식이 버전마다 달라서,
저장한 것과 읽은 것이 어긋나면 `content_hash` 가 매번 흔들린다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from . import contract

DELIM = "---"

_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)


class PageError(ValueError):
    """front-matter 가 없거나 깨진 파일. 조용히 빈 페이지를 만들지 않는다."""


@dataclass
class WikiPage:
    front_matter: dict[str, Any]
    body: str
    #: 저장소 기준 상대 경로 (`measures/ecm-….md`). 저장할 때 채워진다.
    path: str = ""
    errors: list[str] = field(default_factory=list)

    # --- 접근자 ----------------------------------------------------------- #
    @property
    def stable_id(self) -> str:
        return str(self.front_matter.get("stable_id", ""))

    @property
    def type(self) -> str:
        return str(self.front_matter.get("type", ""))

    @property
    def title(self) -> str:
        fm_title = str(self.front_matter.get("title", "")).strip()
        if fm_title:
            return fm_title
        m = re.search(r"^#\s+(.+)$", self.body, re.M)
        return m.group(1).strip() if m else self.stable_id

    @property
    def acl(self) -> str:
        return str(self.front_matter.get("acl", "internal"))

    @property
    def status(self) -> str:
        return str(self.front_matter.get("status", "draft"))

    @property
    def version(self) -> int:
        try:
            return int(self.front_matter.get("version", 1))
        except (TypeError, ValueError):
            return 1

    @property
    def numeric_verified(self) -> bool:
        return bool(self.front_matter.get("numeric_verified", False))

    @property
    def tags(self) -> list[str]:
        return [str(t) for t in (self.front_matter.get("tags") or [])]

    @property
    def related(self) -> list[str]:
        """front-matter 의 related 와 본문 링크의 합집합.

        본문에서만 참조하고 front-matter 에는 안 적는 일이 잦다. 링크 무결성 검사가
        본문 링크를 놓치면 끊어진 링크가 그대로 배포된다.
        """
        declared = [_link_id(x) for x in (self.front_matter.get("related") or [])]
        return list(dict.fromkeys([*declared, *contract.links_in(self.body)]))

    @property
    def source_span(self) -> list[dict[str, Any]]:
        spans = self.front_matter.get("source_span")
        return list(spans) if isinstance(spans, list) else []

    @property
    def filename(self) -> str:
        return f"{self.stable_id}.md"

    def relative_path(self) -> str:
        return f"{contract.directory_of(self.type)}/{self.filename}"

    # --- 직렬화 ----------------------------------------------------------- #
    def dumps(self) -> str:
        fm = yaml.safe_dump(
            self.front_matter, allow_unicode=True, sort_keys=False, default_flow_style=False
        ).rstrip()
        body = self.body.strip()
        return f"{DELIM}\n{fm}\n{DELIM}\n\n{body}\n"

    def refresh_hash(self) -> None:
        self.front_matter["content_hash"] = contract.content_hash(self.body.strip())

    def validate(self) -> contract.ValidationResult:
        return contract.validate(self.front_matter, self.body.strip(), page=self.stable_id)

    def summary(self) -> dict[str, Any]:
        """목록 화면이 쓰는 요약. 본문은 넣지 않는다 — 목록이 통째로 무거워진다."""
        return {
            "stable_id": self.stable_id,
            "type": self.type,
            "title": self.title,
            "acl": self.acl,
            "status": self.status,
            "version": self.version,
            "numeric_verified": self.numeric_verified,
            "owner": str(self.front_matter.get("owner", "")),
            "domain": str(self.front_matter.get("domain", "")),
            "measurement_basis": str(self.front_matter.get("measurement_basis", "")),
            "confidence": str(self.front_matter.get("confidence", "")),
            "tags": self.tags,
            "related": self.related,
            "source_span": self.source_span,
            "updated_at": str((self.front_matter.get("provenance") or {}).get("ingested_at", "")),
            "path": self.path or self.relative_path(),
        }


def _link_id(raw: Any) -> str:
    """`[[eqp-x]]` 든 `eqp-x` 든 ID 하나로 되돌린다."""
    s = str(raw).strip()
    m = contract.WIKILINK_RE.search(s)
    return (m.group(1).strip() if m else s).strip()


def loads(text: str, *, path: str = "") -> WikiPage:
    m = _FRONT.match(text)
    if not m:
        raise PageError(f"front-matter 가 없다: {path or '<메모리>'}")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise PageError(f"front-matter 를 읽을 수 없다: {path or '<메모리>'} — {exc}") from exc
    if not isinstance(fm, dict):
        raise PageError(f"front-matter 가 매핑이 아니다: {path or '<메모리>'}")
    return WikiPage(front_matter=fm, body=m.group(2).strip(), path=path)


def build(*, stable_id: str, page_type: str, title: str, body: str,
          **fm_kwargs: Any) -> WikiPage:
    """본문과 함께 규격을 갖춘 페이지를 만든다. 해시는 본문 기준으로 채운다."""
    body = body.strip()
    fm = contract.new_front_matter(
        stable_id=stable_id, page_type=page_type, body=body, title=title, **fm_kwargs
    )
    return WikiPage(front_matter=fm, body=body)


def link(stable_id: str, label: str = "") -> str:
    return f"[[{stable_id}|{label}]]" if label else f"[[{stable_id}]]"
