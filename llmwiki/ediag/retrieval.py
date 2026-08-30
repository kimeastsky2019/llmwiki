"""검색 — BM25 ⊕ 문자 n-그램을 RRF 로 융합한다.

기획서의 베이스라인은 `BM25 ⊕ Dense → RRF` 다. 이 저장소에는 임베딩 모델도 벡터
DB 도 없다. 그래서 **두 번째 채널을 문자 3-그램 유사도로 대신**한다. 이름을 dense 라
붙이지 않은 이유는, 그렇게 부르면 다음 사람이 임베딩이 이미 있다고 믿기 때문이다.

    Score_RRF(d) = Σ 1 / (k + rank_i(d))          k = 60

| 채널 | 역할 | 이 도메인에서 왜 필요한가 |
|---|---|---|
| `bm25` | 정확 표기 매칭 | 설비 모델명(`SP 125V`), 법규 조항, 사업장명 |
| `ngram` | 표기 흔들림 흡수 | `루츠블로워` ↔ `루츠 블로워` ↔ `루츠부로워` |

세 표기가 실제로 같은 보고서 안에 섞여 있다. 어느 한 채널만 쓰면 반드시 놓친다.

임베딩이 생기면 `Channel` 하나를 더 끼우면 된다 — 융합 함수는 채널이 몇 개든 같다.
그때는 **이 베이스라인 대비 성능으로** 평가한다. 그러라고 베이스라인을 먼저 고정한다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import contract
from .page import WikiPage

#: RRF 상수. 60 은 관례값이다 — 상위권 차이를 과하게 벌리지 않는다.
RRF_K = 60

#: 채널별 융합 가중치. 정확 표기가 더 중요한 도메인이라 BM25 를 조금 높게 둔다.
CHANNEL_WEIGHTS: dict[str, float] = {"bm25": 1.0, "ngram": 0.7}

BM25_K1 = 1.5
BM25_B = 0.75

NGRAM_N = 3

_WORD = re.compile(r"[0-9A-Za-z가-힣]+")


def tokenize(text: str) -> list[str]:
    """어절 + 한글 2-그램. 한글은 어절 안에서 의미가 붙어 있어 어절만으로는 못 찾는다."""
    words = [w.lower() for w in _WORD.findall(text or "")]
    out: list[str] = list(words)
    for w in words:
        if len(w) >= 2 and re.fullmatch(r"[가-힣]+", w):
            out.extend(w[i:i + 2] for i in range(len(w) - 1))
    return out


def ngrams(text: str, n: int = NGRAM_N) -> set[str]:
    flat = re.sub(r"\s+", "", (text or "").lower())
    return {flat[i:i + n] for i in range(max(0, len(flat) - n + 1))}


@dataclass
class Doc:
    stable_id: str
    type: str
    title: str
    acl: str
    status: str
    numeric_verified: bool
    text: str
    tags: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    grams: set[str] = field(default_factory=set)


@dataclass
class Hit:
    stable_id: str
    title: str
    type: str
    acl: str
    status: str
    numeric_verified: bool
    score: float
    ranks: dict[str, int] = field(default_factory=dict)
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class Index:
    """위키 페이지에서 매번 다시 만드는 인덱스.

    인덱스를 파일로 굳혀 두지 않는 이유는 P1 이다. 위키가 진실이고 인덱스는 산출물이라,
    둘이 어긋날 여지를 아예 만들지 않는다. 수백 건 규모에서는 매번 만들어도 빠르다.
    """

    def __init__(self, pages: Iterable[WikiPage]) -> None:
        self.docs: list[Doc] = []
        for p in pages:
            if not p.stable_id or p.errors:
                continue
            text = "\n".join([p.title, " ".join(p.tags), p.body])
            self.docs.append(Doc(
                stable_id=p.stable_id, type=p.type, title=p.title, acl=p.acl,
                status=p.status, numeric_verified=p.numeric_verified, text=text,
                tags=p.tags, tokens=tokenize(text), grams=ngrams(text)))
        self._df: Counter[str] = Counter()
        for d in self.docs:
            self._df.update(set(d.tokens))
        self._avg_len = (sum(len(d.tokens) for d in self.docs) / len(self.docs)
                         if self.docs else 0.0)

    # --- 채널 ------------------------------------------------------------- #
    def _bm25(self, query: str, pool: list[Doc]) -> list[tuple[Doc, float]]:
        q = tokenize(query)
        if not q or not pool:
            return []
        n = len(self.docs)
        scored: list[tuple[Doc, float]] = []
        for d in pool:
            tf = Counter(d.tokens)
            length = len(d.tokens) or 1
            score = 0.0
            for term in q:
                f = tf.get(term, 0)
                if not f:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
                denom = f + BM25_K1 * (1 - BM25_B + BM25_B * length / (self._avg_len or 1))
                score += idf * f * (BM25_K1 + 1) / denom
            if score > 0:
                scored.append((d, score))
        scored.sort(key=lambda x: (-x[1], x[0].stable_id))
        return scored

    def _ngram(self, query: str, pool: list[Doc]) -> list[tuple[Doc, float]]:
        q = ngrams(query)
        if not q or not pool:
            return []
        scored = []
        for d in pool:
            if not d.grams:
                continue
            overlap = len(q & d.grams)
            if not overlap:
                continue
            scored.append((d, overlap / math.sqrt(len(q) * len(d.grams))))
        scored.sort(key=lambda x: (-x[1], x[0].stable_id))
        return scored

    # --- 융합 ------------------------------------------------------------- #
    def search(self, query: str, *, limit: int = 20, acl_max: str = "restricted",
               page_type: str | None = None, status: str | None = None,
               include_deprecated: bool = False) -> list[Hit]:
        """필터는 후보를 줄이는 **코드**로 건다. 지시문으로 거는 필터는 새어 나간다."""
        cap = contract.acl_rank(acl_max)
        pool = [
            d for d in self.docs
            if contract.acl_rank(d.acl) <= cap
            and (page_type is None or d.type == page_type)
            and (status is None or d.status == status)
            and (include_deprecated or d.status != "deprecated")
        ]
        channels = {"bm25": self._bm25(query, pool), "ngram": self._ngram(query, pool)}

        fused: dict[str, float] = {}
        ranks: dict[str, dict[str, int]] = {}
        for name, results in channels.items():
            weight = CHANNEL_WEIGHTS.get(name, 1.0)
            for rank, (doc, _score) in enumerate(results, start=1):
                fused[doc.stable_id] = fused.get(doc.stable_id, 0.0) + weight / (RRF_K + rank)
                ranks.setdefault(doc.stable_id, {})[name] = rank

        by_id = {d.stable_id: d for d in pool}
        hits = [
            Hit(stable_id=sid, title=by_id[sid].title, type=by_id[sid].type,
                acl=by_id[sid].acl, status=by_id[sid].status,
                numeric_verified=by_id[sid].numeric_verified,
                score=round(score, 6), ranks=ranks.get(sid, {}),
                snippet=_snippet(by_id[sid].text, query))
            for sid, score in fused.items()
        ]
        hits.sort(key=lambda h: (-h.score, h.stable_id))
        return hits[:limit]

    def stats(self) -> dict[str, Any]:
        return {
            "documents": len(self.docs),
            "terms": len(self._df),
            "avg_tokens": round(self._avg_len, 1),
            "channels": list(CHANNEL_WEIGHTS),
            "rrf_k": RRF_K,
        }


def _snippet(text: str, query: str, width: int = 140) -> str:
    low = text.lower()
    for term in sorted(set(tokenize(query)), key=len, reverse=True):
        i = low.find(term)
        if i >= 0:
            start = max(0, i - width // 3)
            end = min(len(text), i + width)
            return (("… " if start else "")
                    + re.sub(r"\s+", " ", text[start:end]).strip()
                    + (" …" if end < len(text) else ""))
    return re.sub(r"\s+", " ", text[:width]).strip()
