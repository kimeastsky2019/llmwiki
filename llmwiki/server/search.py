"""문서 로딩 + 검색.

한글 형태소 분석기 없이도 쓸 만하게: 필드 가중치 + 부분 문자열 매칭.
파일명·클래스명·테이블명은 영문, 업무명·본문은 한글이 섞이므로 둘 다 잡는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter


@dataclass
class Doc:
    id: str
    path: Path
    mtime: float
    meta: dict[str, Any]
    body: str
    lower_body: str = ""
    haystack: str = ""


@dataclass
class DocStore:
    docs_dir: Path
    docs: dict[str, Doc] = field(default_factory=dict)

    def refresh(self) -> None:
        if not self.docs_dir.exists():
            return
        seen: set[str] = set()
        for path in sorted(self.docs_dir.glob("*.md")):
            doc_id = path.stem
            seen.add(doc_id)
            mtime = path.stat().st_mtime
            cached = self.docs.get(doc_id)
            if cached and cached.mtime == mtime:
                continue
            post = frontmatter.load(path)
            meta = dict(post.metadata)
            body = post.content
            self.docs[doc_id] = Doc(
                id=doc_id,
                path=path,
                mtime=mtime,
                meta=meta,
                body=body,
                lower_body=body.lower(),
                haystack=_haystack(meta),
            )
        for gone in set(self.docs) - seen:
            self.docs.pop(gone, None)

    def get(self, doc_id: str) -> Doc | None:
        self.refresh()
        return self.docs.get(doc_id)

    def all(self) -> list[Doc]:
        self.refresh()
        return list(self.docs.values())


def _haystack(meta: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("name", "layer", "entry", "urls", "classes", "tables", "sql_ids", "files", "service_ids"):
        value = meta.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif value:
            parts.append(str(value))
    return " ".join(parts).lower()


WEIGHTS = {"name": 20, "table": 12, "class": 8, "url": 8, "sql": 6, "file": 4, "body": 1}


def search(store: DocStore, query: str, limit: int = 40) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return []
    terms = [t for t in re.split(r"\s+", q) if t]

    results: list[dict[str, Any]] = []
    for doc in store.all():
        score = 0
        matched: list[str] = []
        meta = doc.meta

        for term in terms:
            hit = False
            if term in str(meta.get("name", "")).lower():
                score += WEIGHTS["name"]
                hit = True
            for table in meta.get("tables", []) or []:
                if term in str(table).lower():
                    score += WEIGHTS["table"]
                    matched.append(str(table))
                    hit = True
                    break
            for cls in meta.get("classes", []) or []:
                if term in str(cls).lower():
                    score += WEIGHTS["class"]
                    matched.append(str(cls).split(".")[-1])
                    hit = True
                    break
            for url in meta.get("urls", []) or []:
                if term in str(url).lower():
                    score += WEIGHTS["url"]
                    matched.append(str(url))
                    hit = True
                    break
            for sid in meta.get("sql_ids", []) or []:
                if term in str(sid).lower():
                    score += WEIGHTS["sql"]
                    matched.append(str(sid).split(".")[-1])
                    hit = True
                    break
            if not hit and term in doc.haystack:
                score += WEIGHTS["file"]
                hit = True
            count = doc.lower_body.count(term)
            if count:
                score += min(count, 10) * WEIGHTS["body"]
                hit = True
            if not hit:
                score = 0
                break

        if score <= 0:
            continue

        results.append(
            {
                "id": doc.id,
                "name": meta.get("name", doc.id),
                "layer": meta.get("layer", ""),
                "score": score,
                "matched": sorted(set(matched))[:5],
                "snippet": _snippet(doc.body, terms),
                "tables": meta.get("tables", [])[:6],
            }
        )

    results.sort(key=lambda r: -r["score"])
    return results[:limit]


def _snippet(body: str, terms: list[str], width: int = 90) -> str:
    low = body.lower()
    for term in terms:
        i = low.find(term)
        if i >= 0:
            start = max(0, i - width // 2)
            end = min(len(body), i + width)
            text = body[start:end].replace("\n", " ").strip()
            return ("… " if start else "") + text + (" …" if end < len(body) else "")
    return body[:width].replace("\n", " ").strip()
