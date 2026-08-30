"""분석 파이프라인 — 파싱 → 분류 → 커버리지 → 게이트 → 온톨로지.

파이프라인은 한 방향이고, **게이트를 건너뛰는 경로가 없다.**

    PDF ─▶ 4채널 파싱 ─▶ 업종 분류 ─▶ 필수지표 커버리지
                                      │
                                      ▼
                             적재 게이트 (개인정보/AI기본법)
                                      │
                        blocker 있으면 ─┴─▶ 중단. 적재하지 않음
                                      │
                                      ▼
                             비식별 처리 + 마스킹 검산
                                      │
                                      ▼
                      업종 구획(ediag__waste 등)에 채널별 적재  ← store.py
                                      │
                                      ▼
                                온톨로지 그래프

``upload_allowed=False`` 인데 적재할 수 있는 인자는 만들지 않았다. 우회로를 만들면
언젠가 그 경로로 나간다.

`analyze()` 는 **적재하지 않는다.** 사람이 결과를 보고 업종을 확정한 뒤에야
`store.ingest()` 로 넘어간다 — 잘못 분류된 문서는 영영 엉뚱한 구획에서 검색된다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from . import classify, gate, ontology, parse, sources, taxonomy

#: 마스킹으로 해소되지 **않는** 위반. 값을 토큰으로 바꾸는 것만으로는 처리 근거가
#: 생기지 않는 항목이라, 여기 걸리면 마스킹해도 적재 불가다.
UNMASKABLE_RULES = frozenset({"privacy.sensitive"})


@dataclass
class AnalysisResult:
    filename: str
    doc_hash: str
    sector: str
    sector_name: str
    needs_review: bool
    partition: str
    #: 원문 그대로 적재해도 되는가 (진단서에는 담당자 연락처가 거의 항상 있어서 보통 False)
    upload_allowed_raw: bool = False
    #: 비식별 처리를 거치면 적재해도 되는가 (실제 적재 경로의 판단 기준)
    upload_allowed: bool = False
    channels: dict[str, int] = field(default_factory=dict)
    parse_summary: dict = field(default_factory=dict)
    classification: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    gate: dict = field(default_factory=dict)
    masking: dict = field(default_factory=dict)
    graph_stats: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)
    excel_path: str | None = None
    graph: dict | None = None
    #: 4채널 청크. 적재 경로가 32면 PDF 를 다시 파싱하지 않도록 결과에 실어 보낸다.
    #: 응답 JSON 에는 넣지 않는다 (`to_dict()` 가 뺀다).
    chunks: list[dict] = field(default_factory=list)
    #: 채널별 실제 내용 (글·표·그림). 개수만으로는 무엇이 들어왔는지 확인할 수 없어
    #: 화면이 눈으로 대조할 수 있게 만든 것이다. `to_dict()` 는 뺀다 — 적재 저장소의
    #: analysis.json 이 본문을 통째로 복제하게 두면 원문이 구획 밖에 하나 더 생긴다.
    preview: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()
             if k not in ("graph", "chunks", "preview")}
        d["has_graph"] = self.graph is not None
        return d


def _build_preview(doc: parse.ParsedDocument, *, mask: bool) -> dict[str, Any]:
    """채널별 내용을 화면이 그대로 그릴 수 있는 형태로 만든다.

    **원문 적재가 막힌 문서는 화면에도 비식별된 것만 내보낸다.** 게이트가 막은 값을
    같은 화면이 원문 그대로 보여주면 막은 의미가 없다.

    글·그림의 수록 기준은 `parse.to_chunks` 와 같게 맞춘다 (짧은 글 조각 제외,
    로고 제외). 여기만 기준이 다르면 '채널' 카드의 개수와 목록의 줄 수가 어긋나
    어느 쪽이 맞는지 판단할 수 없게 된다. 로고는 빼는 대신 `indexed=False` 로
    남겨 둔다 — 조용히 사라지면 그림이 왜 61개가 아니라 51개인지 알 수 없다.
    """
    def clean(text: str) -> str:
        return gate.mask_text(text)[0] if mask else text

    return {
        "masked": mask,
        "text": [
            {"anchor": b.anchor, "page": b.page, "chars": b.char_len,
             "content": clean(b.text)}
            for b in doc.text_blocks if b.char_len >= parse.MIN_TEXT_CHARS
        ],
        "table": [
            {"anchor": t.anchor, "page": t.page, "caption": clean(t.caption),
             "header": [clean(h) for h in t.header],
             "rows": [[clean(c) for c in row] for row in t.rows],
             "numeric_cells": t.n_numeric_cells}
            for t in doc.tables
        ],
        "image": [
            {"anchor": im.anchor, "page": im.page, "kind": im.kind,
             "width": im.width, "height": im.height,
             "caption": clean(im.nearby_caption), "indexed": im.kind != "logo"}
            for im in doc.images
        ],
    }


def _allowed_after_masking(report: dict, masking: dict) -> bool:
    if not masking.get("clean"):
        return False
    return not any(f["rule"] in UNMASKABLE_RULES for f in report.get("findings", []))


def analyze(
    pdf_path: str,
    *,
    sector_override: str | None = None,
    destination: gate.Destination = gate.UNKNOWN_DESTINATION,
    build_excel: bool = True,
    out_dir: str | None = None,
    diagnosis_id: str | None = None,
    has_output_labeling: bool = False,
    has_prior_notice: bool = False,
    lang: str = "ko",
) -> AnalysisResult:
    """문서 1건을 분석한다. 적재는 하지 않는다 — 화면의 '검토' 단계가 부르는 경로다."""
    # PDF 만이 아니다 — 엑셀(계측 데이터)과 이미지(명판·현장 사진)도 같은
    # ParsedDocument 로 들어온다. 형식 분기는 sources 가 끝낸다.
    doc = sources.parse_document(pdf_path)
    cls = classify.manual(sector_override) if sector_override else classify.classify_document(doc)
    cov = classify.metric_coverage(doc, cls.sector, lang)

    full = doc.searchable_text
    masking = gate.verify_masking(full)
    report = gate.review(
        full, destination=destination, masking_enabled=False, lang=lang,
        has_output_labeling=has_output_labeling, has_prior_notice=has_prior_notice,
    )

    graph = ontology.build_graph(doc, cls, cov, report, diagnosis_id=diagnosis_id)
    check = ontology.validate_graph(graph)

    res = AnalysisResult(
        filename=doc.filename,
        doc_hash=doc.doc_hash,
        sector=cls.sector,
        sector_name=taxonomy.sector_name(cls.sector, lang),
        needs_review=cls.needs_review,
        partition=taxonomy.partition(cls.sector),
        # 원문 적재 가부와 마스킹 후 적재 가부를 나눠서 보고한다. 하나로 합치면
        # "차단인데 적재 허용" 같은 모순된 표시가 나온다.
        upload_allowed_raw=report["upload_allowed"],
        upload_allowed=_allowed_after_masking(report, masking),
        parse_summary=doc.summary(),
        classification=cls.to_dict(lang),
        coverage=cov,
        gate=report,
        masking={k: v for k, v in masking.items() if k != "masked_text"},
        graph_stats=graph["stats"],
        validation={
            "ok": check.ok,
            "errors": len(check.errors),
            "warnings": len(check.warnings),
            "issues": [i.__dict__ for i in check.issues[:20]],
        },
        graph=graph,
    )

    if build_excel:
        out_dir = out_dir or os.path.dirname(os.path.abspath(pdf_path))
        os.makedirs(out_dir, exist_ok=True)
        xlsx = os.path.join(out_dir, f"{doc.doc_hash}_tables.xlsx")
        try:
            res.excel_path = parse.to_excel(doc, xlsx)
        except Exception as exc:  # noqa: BLE001 - 엑셀 실패가 분석 결과를 버리게 하지 않는다
            res.errors.append(f"엑셀 생성 실패: {exc}")

    chunks = parse.to_chunks(doc)
    res.chunks = chunks
    # 원문 적재가 허용된 문서만 원문 그대로 보여준다. 판단 기준은 적재 경로와 같다.
    res.preview = _build_preview(doc, mask=not res.upload_allowed_raw)
    res.channels = {
        ch: sum(1 for c in chunks if c["channel"] == ch) for ch in ("text", "table", "image")
    }
    return res
