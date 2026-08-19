"""위키 생성(ingest 연산) — 추출된 사실을 페이지로 옮긴다.

입력은 `extract.Extraction` 이고 출력은 `WikiPage` 목록이다. 이 모듈이 지키는 규칙은
셋이다.

1. **수치를 새로 만들지 않는다.** 페이지에 적히는 모든 양은 원문에서 뽑았거나
   `calc.py` 가 계산한 것이고, 그 옆에는 언제나 출처(쪽·표)가 붙는다.
2. **모르는 것은 `[검토 필요]` 로 남긴다.** 적용 조건의 일반화처럼 규칙이 답할 수
   없는 항목은 빈칸이 아니라 표시로 남긴다 — 빈칸은 '없음' 으로 읽히고,
   `[검토 필요]` 는 '아직 아무도 안 봤음' 으로 읽힌다.
3. **모든 페이지는 `draft` 로 태어난다.** 검증은 사람이 한다(`review.py`).

ACL 은 타입이 결정한다. 사업장·설비·사용량은 고객사 정보라 `confidential`, 개선안
카드와 인사이트는 사업장 식별정보를 담지 않으므로 `internal`, 법정계수·단가는
`public` 이다. 그래서 개선안 카드는 진단 건을 **직접 링크하지 않는다** — 낮은 등급
페이지가 높은 등급 페이지를 참조하면 그 링크 자체가 정보를 흘린다(lint 의
`acl.inheritance`). 사례는 진단 페이지 쪽에서 걸고, 카드에서는 역링크로 보여 준다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..kb import gate
from . import calc, contract, extract as ex_mod, page as page_mod, terms
from .page import WikiPage
from .units import UnitTable, load

#: 타입별 기본 접근 등급. 화면에서 개별로 올릴 수는 있어도 내리는 경로는 두지 않는다.
ACL_BY_TYPE: dict[str, str] = {
    "source": "confidential",
    "diagnosis": "confidential",
    "facility": "confidential",
    "equipment": "confidential",
    "metric": "confidential",
    "measure": "internal",
    "concept": "internal",
    "vendor": "internal",
    "regulation": "public",
}

REVIEW_MARK = "[검토 필요]"


@dataclass
class BuildOptions:
    """생성 옵션. `site_key` 만 사람이 정하고 나머지는 기본값으로 둔다.

    `site_key` 를 사람이 정하는 이유: `stable_id` 는 파서를 고쳐도, 보고서를 다시
    받아도 같아야 한다. 문서 해시에서 뽑으면 재발행 한 번에 ID 가 전부 갈린다.
    """

    site_key: str = ""
    owner: str = "energy-team"
    ingested_by: str = "rule-engine"
    pipeline_version: str = "v0.1.0"
    domain: str = "industrial"
    unit_system: str = "SI"
    mask: bool = True


@dataclass
class BuildResult:
    pages: list[WikiPage] = field(default_factory=list)
    extraction: Any = None
    warnings: list[str] = field(default_factory=list)
    site_key: str = ""
    period: str = ""

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for p in self.pages:
            by_type[p.type] = by_type.get(p.type, 0) + 1
        return {
            "pages": len(self.pages),
            "by_type": dict(sorted(by_type.items())),
            "site_key": self.site_key,
            "period": self.period,
            "warnings": list(self.warnings),
            "extraction": self.extraction.summary() if self.extraction else {},
            "verified_pages": sum(1 for p in self.pages if p.numeric_verified),
        }


# --------------------------------------------------------------------------- #
# 작은 도구들
# --------------------------------------------------------------------------- #
def _mask(text: str, enabled: bool = True) -> str:
    """본문에 들어가는 원문 조각은 반드시 비식별을 거친다.

    위키는 사내 공유물이라 "원문에 있으니 그대로" 가 통하지 않는다. 마스킹은 값을
    지우지 않고 종류를 남긴 토큰으로 바꾼다 — `[전화번호]` 가 남아야 '여기에 연락처가
    있었다' 는 사실이 검색·감리에서 보존된다.
    """
    if not enabled or not text:
        return text
    masked, _ = gate.mask_text(text)
    return masked


def _num(value: Any, digits: int = 0) -> str:
    if value is None:
        return REVIEW_MARK
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{f:,.{digits}f}"


def _md_table(header: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    out = ["| " + " | ".join(header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        cells = [str(c).replace("|", "\\|") for r_ in [r] for c in r_]
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


def _period_of(doc: Any) -> str:
    """보고서 기준 연월. 표지의 `2026년 4월` 이 가장 신뢰할 만하다."""
    head = "\n".join(b.text for b in doc.text_blocks[:3])
    m = re.search(r"(20\d{2})\s*년\s*(\d{1,2})\s*월", head)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(20\d{2})\s*년", doc.full_text)
    return f"{m.group(1)}-00" if m else "unknown"


def _throughput_tpd(doc: Any) -> float | None:
    """1일 처리용량(톤/일). 원단위의 분모라 없으면 원단위를 만들지 않는다."""
    for pattern in (r"처리용량[^\n]{0,20}?([\d,]+)\s*\(?\s*(?:ton|톤)",
                    r"허가용량[^\n]{0,30}?([\d,]+)\s*(?:톤|ton)\s*/?\s*일"):
        m = re.search(pattern, doc.full_text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _operating_days(doc: Any) -> float | None:
    m = re.search(r"연간\s*(\d{2,3})\s*일\s*가동", doc.full_text)
    return float(m.group(1)) if m else None


def _span(doc: Any, pages: list[int], section: str = "", anchor: str = "") -> dict[str, Any]:
    return ex_mod.Span(doc=doc.filename, pages=sorted(set(pages)),
                       section=section, anchor=anchor).to_dict()


def _verified(checks: list[calc.Check], pages: list[int]) -> tuple[bool, list[calc.Check]]:
    """해당 쪽에서 나온 검산이 모두 통과했는가.

    관련 검산이 하나도 없으면 통과로 본다 — 계산이 없는 페이지(설비 제원처럼 원문에
    적힌 값을 옮기기만 한 페이지)까지 미검산으로 표시하면, 정작 **검산에 실패한**
    페이지가 묻힌다. 계산이 있는데 틀린 경우만 False 다.
    """
    want = {f"p{p}" for p in pages}
    mine = [c for c in checks if any(w in (c.source or "") for w in want)]
    return all(c.ok for c in mine), mine


def _checks_for(checks: list[calc.Check], needle: str) -> tuple[bool, list[calc.Check]]:
    """라벨로 검산을 고른다. 표 한 장에 여러 행이 있으면 쪽 단위 판정은 너무 거칠다 —
    한 행이 틀렸다고 그 표에서 나온 페이지를 전부 미검산으로 만들면 안 된다."""
    mine = [c for c in checks if needle in (c.label or "")]
    return all(c.ok for c in mine), mine


def _checks_table(checks: list[calc.Check]) -> str:
    rows = []
    for c in checks:
        rows.append([
            "✅" if c.ok else "❌",
            c.label,
            _num(c.stated, 2) if c.stated is not None else "—",
            _num(c.computed, 2),
            c.unit or "",
            c.formula or "",
            c.source or "",
        ])
    return _md_table(["", "항목", "원문", "재계산", "단위", "산식", "출처"], rows)


# --------------------------------------------------------------------------- #
# 본체
# --------------------------------------------------------------------------- #
def build(doc: Any, *, options: BuildOptions | None = None,
          extraction: Any = None, analysis: dict[str, Any] | None = None,
          table: UnitTable | None = None) -> BuildResult:
    """문서 1건 → 위키 페이지 목록. 저장하지 않는다 (저장은 `store.WikiStore`)."""
    opts = options or BuildOptions()
    t = table or load()
    ex = extraction or ex_mod.extract(doc, t)

    site = contract.slug(opts.site_key) if opts.site_key else ""
    warnings: list[str] = []
    if not site:
        site = f"d{doc.doc_hash[:8]}"
        warnings.append(
            "사업장 키를 지정하지 않아 문서 해시로 대신했다. 보고서가 재발행되면 "
            "ID 가 바뀐다 — 관리자 화면에서 사업장 키를 지정해 다시 생성한다.")
    period = _period_of(doc)

    ids = {
        "source": f"src-{site}-{period}",
        "diagnosis": f"dgn-{site}-{period}",
        "facility": f"fac-{site}",
    }

    pages: list[WikiPage] = []
    pages.extend(_regulation_pages(doc, t, opts))
    equipment_pages = _equipment_pages(doc, ex, opts, site, ids)
    metric_pages = _metric_pages(doc, ex, opts, site, ids, t)
    measure_pages, measure_ids = _measure_pages(doc, ex, opts, ids)
    concept_pages = _concept_pages(doc, ex, opts, measure_ids)
    pages.extend(equipment_pages)
    pages.extend(metric_pages)
    pages.extend(measure_pages)
    pages.extend(concept_pages)
    pages.append(_facility_page(doc, ex, opts, ids,
                                [p.stable_id for p in equipment_pages],
                                [p.stable_id for p in metric_pages]))
    pages.append(_diagnosis_page(doc, ex, opts, ids,
                                 [p.stable_id for p in equipment_pages],
                                 [p.stable_id for p in metric_pages],
                                 measure_ids,
                                 [p.stable_id for p in concept_pages]))
    pages.append(_source_page(doc, ex, opts, ids, analysis))

    if ex.failed:
        warnings.append(
            f"수치 검산 {len(ex.failed)}건이 실패했다. 해당 값을 인용하는 페이지는 "
            f"numeric_verified=false 로 남으며 서비스 응답에서 인용되지 않는다.")
    if ex.pii_dropped:
        warnings.append(f"개인정보 항목 {ex.pii_dropped}건은 위키로 옮기지 않았다.")

    return BuildResult(pages=pages, extraction=ex, warnings=warnings,
                       site_key=site, period=period)


def _fm(opts: BuildOptions, **kw: Any) -> dict[str, Any]:
    kw.setdefault("owner", opts.owner)
    kw.setdefault("ingested_by", opts.ingested_by)
    kw.setdefault("pipeline_version", opts.pipeline_version)
    kw.setdefault("domain", opts.domain)
    kw.setdefault("unit_system", opts.unit_system)
    return kw


# --------------------------------------------------------------------------- #
# 원문 페이지
# --------------------------------------------------------------------------- #
def _source_page(doc: Any, ex: Any, opts: BuildOptions, ids: dict[str, str],
                 analysis: dict[str, Any] | None) -> WikiPage:
    summary = doc.summary()
    body = [
        f"# 원문 — {_mask(doc.filename, opts.mask)}",
        "",
        "## 문서 개요",
        "",
        _md_table(["항목", "값"], [
            ["쪽수", _num(summary["pages"])],
            ["문서 해시", doc.doc_hash],
            ["표", _num(summary["tables"])],
            ["표 데이터 행", _num(summary["table_rows"])],
            ["수치 셀", _num(summary["numeric_cells"])],
            ["그림", _num(summary["images"])],
        ]),
        "",
        "## 적재 판정",
        "",
    ]
    if analysis:
        g = analysis.get("gate") or {}
        body += [
            _md_table(["항목", "값"], [
                ["업종", f"{analysis.get('sector_name','')} ({analysis.get('sector','')})"],
                ["게이트 판정", str(g.get("verdict", ""))],
                ["개인정보 탐지", _num(g.get("pii_detected"))],
                ["원문 그대로 적재", "허용" if analysis.get("upload_allowed_raw") else "불가"],
                ["비식별 후 적재", "허용" if analysis.get("upload_allowed") else "불가"],
            ]),
            "",
        ]
    else:
        body += ["> 게이트 판정 정보 없이 생성되었다. " + REVIEW_MARK, ""]

    body += [
        "## 수치 검산 요약",
        "",
        f"- 검산 {len(ex.checks)}건 중 실패 {len(ex.failed)}건",
        "",
    ]
    if ex.failed:
        body += ["### 실패한 검산", "", _checks_table(ex.failed), "",
                 "> 실패는 이 위키의 오류가 아니라 **원문과 재계산의 불일치**다. "
                 "원문이 틀렸는지 우리 입력이 틀렸는지는 사람이 판정한다.", ""]

    body += [
        "## 관련",
        "",
        f"{page_mod.link(ids['diagnosis'])} · {page_mod.link(ids['facility'])}",
    ]

    verified, _ = _verified(ex.checks, list(range(1, doc.n_pages + 1)))
    return page_mod.build(
        stable_id=ids["source"], page_type="source",
        title=f"원문 — {doc.filename}", body="\n".join(body),
        source_span=[_span(doc, list(range(1, doc.n_pages + 1)), "전체")],
        acl=ACL_BY_TYPE["source"], numeric_verified=verified,
        measurement_basis="documented", confidence="high",
        tags=["원문", "에너지진단"],
        related=[ids["diagnosis"], ids["facility"]],
        extra={"doc_hash": doc.doc_hash},
        **_fm(opts))


# --------------------------------------------------------------------------- #
# 진단 페이지
# --------------------------------------------------------------------------- #
def _diagnosis_page(doc: Any, ex: Any, opts: BuildOptions, ids: dict[str, str],
                    equipment_ids: list[str], metric_ids: list[str],
                    measure_ids: list[str], concept_ids: list[str]) -> WikiPage:
    inv = ex.investment or {}
    saving = ex_mod._annual_saving_kwon(ex)
    payback = (calc.payback_years(inv["total_kwon"], saving)
               if inv.get("total_kwon") and saving else None)

    rows = []
    for f in ex.aggregate:
        if f.fields["group"].replace(" ", "") != "계":
            continue
        rows.append([
            f.fields["item"], f.fields["unit"],
            _num(f.fields["before"], 2), _num(f.fields["after"], 2),
            _num(f.fields["before"] - f.fields["after"], 2),
        ])

    body = [
        f"# 진단 — {_mask(_facility_name(ex) or doc.filename, opts.mask)}",
        "",
        "## 개요",
        "",
        _md_table(["항목", "값", "출처"], [
            ["보고서", page_mod.link(ids["source"]), "원문"],
            ["사업장", page_mod.link(ids["facility"]), "원문 Ⅰ.1"],
            ["투자비(천원)", _num(inv.get("total_kwon")), "투자비 표"],
            ["연간 절감금액(천원)", _num(saving), "집계표 계·금액"],
            ["회수기간(년)", _num(payback, 2) if payback is not None else REVIEW_MARK,
             "투자비 ÷ 연간 절감금액"],
            ["원문 표기 회수기간(년)", _num(inv.get("stated_payback_years"), 1)
             if inv.get("stated_payback_years") is not None else REVIEW_MARK, "원문"],
        ]),
        "",
        "## 사업 전·후 (계)",
        "",
        _md_table(["항목", "단위", "개선전", "개선후", "절감"], rows) or REVIEW_MARK,
        "",
        "> 수치는 이 페이지에서 생성하지 않는다. 원문 표에서 읽고 `llmwiki.ediag.calc` 가"
        " 재계산해 대조한 값이다.",
        "",
        "## 검산 결과",
        "",
        _checks_table(ex.checks[:40]) or "검산 대상이 없다.",
        "",
    ]
    if len(ex.checks) > 40:
        body += [f"> 검산 {len(ex.checks)}건 중 40건만 표시한다.", ""]

    if measure_ids:
        body += ["## 적용 개선안", "",
                 *[f"- {page_mod.link(m)}" for m in measure_ids], ""]
    if equipment_ids:
        body += ["## 대상 설비", "",
                 *[f"- {page_mod.link(e)}" for e in equipment_ids], ""]
    if metric_ids:
        body += ["## 지표", "", *[f"- {page_mod.link(m)}" for m in metric_ids], ""]
    if concept_ids:
        body += ["## 도출된 인사이트", "",
                 *[f"- {page_mod.link(c)}" for c in concept_ids], ""]

    verified, _ = _verified(ex.checks, list(range(1, doc.n_pages + 1)))
    return page_mod.build(
        stable_id=ids["diagnosis"], page_type="diagnosis",
        title=f"진단 {_period_of(doc)} — {_facility_name(ex) or doc.filename}",
        body="\n".join(body),
        source_span=[_span(doc, [p for p in range(1, doc.n_pages + 1)], "전체")],
        acl=ACL_BY_TYPE["diagnosis"], numeric_verified=verified,
        measurement_basis="mixed", confidence="high" if verified else "medium",
        measurement_period=_period_of(doc),
        tags=["진단", "ESCO"],
        related=[ids["source"], ids["facility"], *equipment_ids, *metric_ids,
                 *measure_ids, *concept_ids],
        **_fm(opts))


def _facility_name(ex: Any) -> str:
    for key in ("업체명", "업체 명"):
        if key in ex.facility:
            return str(ex.facility[key])
    return ""


# --------------------------------------------------------------------------- #
# 사업장 페이지
# --------------------------------------------------------------------------- #
def _facility_page(doc: Any, ex: Any, opts: BuildOptions, ids: dict[str, str],
                   equipment_ids: list[str], metric_ids: list[str]) -> WikiPage:
    rows = [[k, _mask(str(v), opts.mask)]
            for k, v in ex.facility.items() if not k.startswith("_")]
    tpd = _throughput_tpd(doc)
    days = _operating_days(doc)
    if tpd:
        rows.append(["1일 처리용량(톤/일)", _num(tpd)])
    if days:
        rows.append(["연간 가동일수(일)", _num(days)])

    body = [
        f"# 사업장 — {_mask(_facility_name(ex) or '미상', opts.mask)}",
        "",
        "## 일반현황",
        "",
        _md_table(["항목", "값"], rows) or REVIEW_MARK,
        "",
        f"> 대표자·담당자·연락처·사업자등록번호 등 개인정보 {ex.pii_dropped}건은 "
        "위키로 옮기지 않았다. 원문에는 남아 있다.",
        "",
    ]
    if equipment_ids:
        body += ["## 보유 설비", "", *[f"- {page_mod.link(e)}" for e in equipment_ids], ""]
    if metric_ids:
        body += ["## 에너지 지표", "", *[f"- {page_mod.link(m)}" for m in metric_ids], ""]
    body += ["## 진단 이력", "", f"- {page_mod.link(ids['diagnosis'])}", ""]

    span_pages = [ex.facility.get("_span", {}).get("pages", [1])[0]] if ex.facility else [1]
    return page_mod.build(
        stable_id=ids["facility"], page_type="facility",
        title=_facility_name(ex) or "사업장", body="\n".join(body),
        source_span=[_span(doc, span_pages, "Ⅰ.1 일반현황")],
        acl=ACL_BY_TYPE["facility"], numeric_verified=True,
        measurement_basis="documented", confidence="high",
        tags=["사업장"],
        related=[ids["diagnosis"], *equipment_ids, *metric_ids],
        **_fm(opts))


# --------------------------------------------------------------------------- #
# 설비 페이지
# --------------------------------------------------------------------------- #
def _equipment_pages(doc: Any, ex: Any, opts: BuildOptions, site: str,
                     ids: dict[str, str]) -> list[WikiPage]:
    out: list[WikiPage] = []
    for fact in ex.equipment:
        g = fact.fields
        cap = f"{g['capacity']:g}{g['capacity_unit']}" if g["capacity"] is not None else ""
        # `0.5t/h` → `0-5th`. ID 에 점과 슬래시가 들어가면 파일명·URL 에서 갈린다.
        suffix = contract.slug(f"{g['term']}-{cap.replace('.', '-').replace('/', '')}")
        stable_id = f"eqp-{site}-{suffix or g['term']}"

        inst_rows = [[i["location"], _num(i["count"])] for i in g["installations"]]
        body = [
            f"# {g['name']} {cap}".strip(),
            "",
            "## 제원",
            "",
            _md_table(["항목", "값"], [
                ["용량", cap or REVIEW_MARK],
                ["대수", _num(g["total_count"])],
                ["모델", g["model"] or REVIEW_MARK],
                ["제작사", g["maker"] or REVIEW_MARK],
                ["제작년도", g["year"] or REVIEW_MARK],
                ["연료", g["fuel"] or "—"],
            ]),
            "",
        ]
        if inst_rows:
            body += ["## 설치 현황", "", _md_table(["위치", "대수"], inst_rows), ""]

        mine = [m for m in ex.measurements]
        if mine and g["term"] == "roots-blower":
            body += [
                "## 현장 계측",
                "",
                _md_table(["기번", "측정 시각", "평균 전력(kW)", "부하율(%)"],
                          [[m.fields["tag"], m.fields["when"],
                            _num(m.fields["avg_kw"], 1), _num(m.fields["load_pct"], 0)]
                           for m in mine]),
                "",
            ]
            over = [m for m in mine if m.fields["load_pct"] > 100]
            if over:
                body += [
                    f"> 부하율 100%를 넘는 측정이 {len(over)}건이다 — 정격을 넘겨 도는 "
                    "상태이므로 노후·과부하를 의심할 근거가 된다.",
                    "",
                ]

        body += ["## 관련", "",
                 f"{page_mod.link(ids['facility'])} · {page_mod.link(ids['diagnosis'])}"]

        if g["needs_naming"]:
            body += ["", f"> 설비 명칭을 용어 사전에서 찾지 못했다. {REVIEW_MARK} "
                         "— `llmwiki/ediag/terms.py` 에 용어를 추가하고 다시 생성한다."]

        verified, _ = _verified(ex.checks, fact.span.pages)
        out.append(page_mod.build(
            stable_id=stable_id, page_type="equipment",
            title=f"{g['name']} {cap}".strip(), body="\n".join(body),
            source_span=[_span(doc, fact.span.pages, "설비현황", fact.span.anchor)],
            acl=ACL_BY_TYPE["equipment"], numeric_verified=verified,
            measurement_basis="measured" if (ex.measurements and g["term"] == "roots-blower")
            else "documented",
            confidence="high",
            tags=["설비", g["term"]],
            related=[ids["facility"], ids["diagnosis"]],
            # 제원을 front-matter 에도 남긴다. 본문 표를 파싱해 문서 간 모순을 찾는 것은
            # 서식이 바뀌는 순간 깨진다 — 비교는 구조화된 값끼리 해야 한다.
            extra={"equipment": {
                "term": g["term"], "capacity": g["capacity"],
                "capacity_unit": g["capacity_unit"], "model": g["model"],
                "maker": g["maker"], "year": g["year"], "count": g["total_count"],
            }},
            **_fm(opts)))
    return out


# --------------------------------------------------------------------------- #
# 지표 페이지
# --------------------------------------------------------------------------- #
#: 집계표 항목 → 지표 ID 조각·단위. 닫힌 표라 표기가 흔들려도 ID 는 흔들리지 않는다.
METRIC_KEYS: tuple[tuple[str, str, str], ...] = (
    ("전력량", "kwh", "kWh/y"),
    ("연료량", "kg", "kg/y"),
    ("에너지량", "toe", "toe/y"),
    ("온실가스량", "ghg", "tCO2eq/y"),
    ("금액", "cost", "천원/y"),
)


def _metric_pages(doc: Any, ex: Any, opts: BuildOptions, site: str, ids: dict[str, str],
                  t: UnitTable) -> list[WikiPage]:
    out: list[WikiPage] = []
    seen: set[str] = set()
    for fact in ex.aggregate:
        f = fact.fields
        group = f["group"].replace(" ", "")
        key = next((k for k in METRIC_KEYS if k[0] in f["item"]), None)
        if key is None:
            continue
        scope = {"계": "total", "전기": "electricity", "LPG": "lpg"}.get(group, contract.slug(group))
        stable_id = f"mtr-{site}-{scope}-{key[1]}"
        if stable_id in seen:
            continue
        seen.add(stable_id)

        s = calc.savings(f["before"], f["after"], key[2], f"{group} {f['item']}")
        verified, mine = _checks_for(ex.checks, f"{f['group']} {f['item']}")
        body = [
            f"# {group} {f['item']} — {'사업 전후' if group else ''}".strip(),
            "",
            "## 값",
            "",
            _md_table(["구분", "값", "단위"], [
                ["개선전", _num(s.before, 2), key[2]],
                ["개선후", _num(s.after, 2), key[2]],
                ["절감", _num(s.saved, 2), key[2]],
                ["절감률", _num(s.to_dict()["rate_pct"], 1) + " %", ""],
            ]),
            "",
            f"> 출처: 원문 p{fact.span.pages[0]} 사업 전·후 집계표. "
            "절감·절감률은 `llmwiki.ediag.calc` 가 계산한다.",
            "",
        ]
        if mine:
            body += ["## 검산", "", _checks_table(mine), ""]
        reg = ("reg-ghg-emission-factor" if key[1] == "ghg"
               else "reg-energy-unit-price" if key[1] == "cost"
               else "reg-energy-conversion-factor")
        body += ["## 관련", "",
                 f"{page_mod.link(ids['diagnosis'])} · {page_mod.link(ids['facility'])}"
                 f" · {page_mod.link(reg)}"]

        out.append(page_mod.build(
            stable_id=stable_id, page_type="metric",
            title=f"{group} {f['item']}", body="\n".join(body),
            source_span=[_span(doc, fact.span.pages, "사업 전·후 집계표", fact.span.anchor)],
            acl=ACL_BY_TYPE["metric"], numeric_verified=verified,
            measurement_basis="mixed", confidence="high" if verified else "low",
            measurement_period=_period_of(doc),
            tags=["지표", scope],
            related=[ids["diagnosis"], ids["facility"], reg],
            **_fm(opts)))

    intensity = _intensity_page(doc, ex, opts, site, ids, t)
    if intensity is not None:
        out.append(intensity)
    return out


def _intensity_page(doc: Any, ex: Any, opts: BuildOptions, site: str, ids: dict[str, str],
                    t: UnitTable) -> WikiPage | None:
    """에너지 원단위. 분모(처리량)를 못 찾으면 만들지 않는다.

    분모를 추정해서 만들면 업종 벤치마크가 조용히 오염된다. 없는 편이 낫다.
    """
    tpd = _throughput_tpd(doc)
    days = _operating_days(doc)
    total_toe = next((f.fields["before"] for f in ex.aggregate
                      if f.fields["group"].replace(" ", "") == "계"
                      and "에너지량" in f.fields["item"]), None)
    if not (tpd and days and total_toe):
        return None
    throughput = tpd * days
    value = calc.energy_intensity(total_toe, throughput)
    body = [
        "# 에너지 원단위 — 처리량 1톤당",
        "",
        _md_table(["항목", "값", "단위", "출처"], [
            ["연간 에너지사용량(개선전)", _num(total_toe, 2), "toe/y", "집계표 계·에너지량"],
            ["1일 처리용량", _num(tpd), "톤/일", "원문 진단 대상"],
            ["연간 가동일수", _num(days), "일", "원문 산정 주기"],
            ["연간 처리량", _num(throughput), "톤/y", "처리용량 × 가동일수"],
            ["**에너지 원단위**", f"{value:.4f}", "toe/톤", "계산"],
        ]),
        "",
        "> 분모는 업종마다 다르다(건물 ㎡, 폐기물처리 처리톤). 분모가 다른 원단위를 "
        "같은 표에 놓으면 벤치마크가 깨진다 — 업종 구획이 그래서 있다.",
        "",
        f"> 처리량은 **허가·설계 기준**이라 실제 반입량과 다를 수 있다. {REVIEW_MARK}",
        "",
        "## 관련",
        "",
        f"{page_mod.link(ids['diagnosis'])} · {page_mod.link(ids['facility'])}",
    ]
    return page_mod.build(
        stable_id=f"mtr-{site}-energy-intensity", page_type="metric",
        title="에너지 원단위 (toe/처리톤)", body="\n".join(body),
        source_span=[_span(doc, [1], "진단 대상 · 집계표")],
        acl=ACL_BY_TYPE["metric"], numeric_verified=False,
        measurement_basis="mixed", confidence="medium",
        measurement_period=_period_of(doc),
        tags=["지표", "원단위", "벤치마크"],
        related=[ids["diagnosis"], ids["facility"]],
        **_fm(opts))


# --------------------------------------------------------------------------- #
# 개선안(ECM) 카드
# --------------------------------------------------------------------------- #
#: 개선안 제목에 붙는 행위. 이것이 없으면 설비 설명이지 개선안이 아니다.
MEASURE_VERB = re.compile(r"도입|개체|개채|교체|설치|철거|개선|보강|산출서|전환")

#: 목차 줄. 점선 리더(`····17`)가 붙어 있어 제목처럼 보이지만 내용이 없다.
TOC_LINE = re.compile(r"[·.\u2026]{6,}")


def _readable(lines: list[str], minimum: int = 15) -> list[str]:
    """요약에 쓸 만한 줄만 남긴다. 목차와 한 토막짜리 소제목은 버린다."""
    out = []
    for line in lines:
        text = TOC_LINE.sub(" ", line).strip()
        if len(text) < minimum:
            continue
        out.append(re.sub(r"\s{2,}", " ", text))
    return out


def _measure_pages(doc: Any, ex: Any, opts: BuildOptions,
                   ids: dict[str, str]) -> tuple[list[WikiPage], list[str]]:
    """세부개선사항 제목에서 ECM 카드를 만든다.

    카드 ID 는 **사업장에 매이지 않는다**. 같은 개선안이 다음 진단에서 다시 나오면
    같은 카드에 사례가 쌓여야 재사용 자산이 된다.
    """
    found: dict[str, dict[str, Any]] = {}
    for block in doc.text_blocks:
        for line in block.text.splitlines():
            if not re.match(r"^\s*\d+\s*[.,)]\s*\S", line):
                continue
            if TOC_LINE.search(line):
                # 목차 줄이다. 제목 어휘는 같지만 내용이 없고, 여기서 걸러 두지 않으면
                # 요약과 근거 스팬이 3쪽(목차)을 가리킨다.
                continue
            if not MEASURE_VERB.search(line):
                # 설비 설명 문장("3) 이중자켓 연소로 (전단 탈취 연소로)")이 개선안 제목으로
                # 올라오는 것을 막는다. 개선안 제목에는 언제나 행위가 붙는다.
                continue
            hit = terms.match_measure(line)
            if hit is None:
                continue
            mid, title = hit
            rec = found.setdefault(mid, {"title": title, "pages": [], "lines": []})
            if block.page not in rec["pages"]:
                rec["pages"].append(block.page)
            rec["lines"].append(line.strip())
            # 제목 다음 줄들이 실제 설명이다. 제목만으로는 카드가 비어 보인다.
            after = block.text.splitlines()
            if line in after:
                start = after.index(line) + 1
                rec["lines"].extend(after[start:start + 4])

    scope = [n for n in ex.narratives if n["kind"] in ("scope", "improvement")]
    saving = ex_mod._annual_saving_kwon(ex)
    inv = ex.investment or {}
    payback = (calc.payback_years(inv["total_kwon"], saving)
               if inv.get("total_kwon") and saving else None)

    # 카드가 인용하는 수치는 투자비·연간 절감금액·회수기간뿐이다. 그 검산만 본다.
    cited_ok = all(
        c.ok for c in ex.checks
        if "회수기간" in (c.label or "") or "계 금액" in (c.label or "")
    )

    out: list[WikiPage] = []
    for mid, rec in found.items():
        cond_rows = []
        for fact in ex.power:
            if fact.fields["is_total"]:
                cond_rows.append(["연간 가동시간", _num(fact.fields["hours"]), "h/y", "전력 산정표"])
                cond_rows.append(["부하율", _num(fact.fields["load_pct"]), "%", "전력 산정표"])
                break
        tpd = _throughput_tpd(doc)
        if tpd:
            cond_rows.append(["처리용량", _num(tpd), "톤/일", "진단 대상"])

        body = [
            f"# {rec['title']}",
            "",
            "## 요약",
            "",
            _mask(" ".join(_readable(rec["lines"])[:2]) or REVIEW_MARK, opts.mask),
            "",
            "## 적용 조건",
            "",
            "이 진단에서 관측된 조건이다. **일반화 조건은 아직 없다** — 사례가 2건 이상 "
            f"쌓이면 채운다. {REVIEW_MARK}",
            "",
            _md_table(["항목", "값", "단위", "출처"], cond_rows) or REVIEW_MARK,
            "",
            "## 산출 근거",
            "",
            "| 항목 | 값 | 산출 |",
            "|---|---|---|",
            f"| 투자비 | {_num(inv.get('total_kwon'))} 천원 | 원문 투자비 표 (사업 전체) |",
            f"| 연간 절감금액 | {_num(saving)} 천원 | 집계표 계·금액 (사업 전체) |",
            f"| 회수기간 | {_num(payback, 2) if payback is not None else REVIEW_MARK} 년 |"
            " `calc.payback_years` |",
            "",
            "> 이 보고서의 경제성은 **사업 전체** 기준으로만 산출되어 있다. 개선안별 "
            f"분해는 원문에 없다. {REVIEW_MARK}",
            "",
            "## 적용 사례",
            "",
            "> 사례는 이 카드에 직접 적지 않는다. 진단 건은 `confidential` 이고 이 카드는 "
            "`internal` 이라, 낮은 등급이 높은 등급을 참조하면 링크 자체가 정보를 흘린다. "
            "사례는 진단 페이지가 이 카드를 걸고, 화면이 **역링크**로 보여 준다.",
            "",
            "## 관련",
            "",
            f"{page_mod.link('reg-energy-unit-price')} · "
            f"{page_mod.link('reg-ghg-emission-factor')}",
        ]
        cited = [(n["page"], line) for n in scope for line in _readable(n["lines"], 20)]
        if cited:
            body += ["", "## 원문 근거", "",
                     *[f"- (p{page}) {_mask(line, opts.mask)}" for page, line in cited[:3]]]

        out.append(page_mod.build(
            stable_id=mid, page_type="measure", title=rec["title"], body="\n".join(body),
            source_span=[_span(doc, rec["pages"], "Ⅲ 세부개선사항")],
            acl=ACL_BY_TYPE["measure"], numeric_verified=cited_ok,
            measurement_basis="mixed", confidence="medium",
            tags=["개선안", "ESCO", opts.domain],
            related=["reg-energy-unit-price", "reg-ghg-emission-factor"],
            **_fm(opts)))
    return out, list(found)


# --------------------------------------------------------------------------- #
# 법규·계수 페이지 (사업장과 무관 — 재사용 자산)
# --------------------------------------------------------------------------- #
def _regulation_pages(doc: Any, t: UnitTable, opts: BuildOptions) -> list[WikiPage]:
    groups: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("reg-energy-conversion-factor", "에너지 열량 환산계수",
         ("elec.toe_per_mwh", "lpg.toe_per_ton", "lpg.lhv_kcal_per_kg", "steam.kcal_per_ton")),
        ("reg-ghg-emission-factor", "온실가스 배출계수",
         ("elec.tco2eq_per_mwh", "lpg.tco2eq_per_ton")),
        ("reg-energy-unit-price", "에너지원별 단가",
         ("price.elec_won_per_kwh", "price.lpg_won_per_kg", "price.lpg_won_per_nm3")),
    )
    out: list[WikiPage] = []
    for stable_id, title, codes in groups:
        rows = []
        notes: list[str] = []
        for code in codes:
            f = t.factor(code)
            days = f.expires_in()
            rows.append([f.label, _num(f.value, 4), f.unit, f.valid_from, f.valid_until,
                         f.source])
            if f.mislabeled_as:
                notes.append(
                    f"- **{f.label}** 의 분모는 `{f.unit}` 다. 원문에는 "
                    f"`{f.mislabeled_as}` 로 적힌 곳이 있는데, 그대로 곱하면 값이 틀린다.")
            if days is not None and days <= 90:
                notes.append(f"- **{f.label}** 의 유효기간이 {days}일 남았다.")
        body = [
            f"# {title}",
            "",
            f"`data/units.yaml` v{t.version} (기준 {t.standard}) 에서 생성된다. "
            "**이 표를 직접 고치지 않는다** — 단위 테이블을 고치고 다시 생성한다 (P1).",
            "",
            _md_table(["계수", "값", "단위", "유효 시작", "유효 종료", "근거"], rows),
            "",
        ]
        if notes:
            body += ["## 주의", "", *notes, ""]
        out.append(page_mod.build(
            stable_id=stable_id, page_type="regulation", title=title,
            body="\n".join(body),
            source_span=[{"doc": "llmwiki/ediag/data/units.yaml", "pages": [],
                          "section": t.version}],
            acl=ACL_BY_TYPE["regulation"], numeric_verified=True,
            measurement_basis="documented", confidence="high",
            tags=["법규", "계수"], related=[],
            extra={"valid_until": min((t.factor(c).valid_until for c in codes), default="")},
            **_fm(opts)))
    return out


# --------------------------------------------------------------------------- #
# 인사이트 페이지 — 규칙이 찾은 패턴만
# --------------------------------------------------------------------------- #
def _concept_pages(doc: Any, ex: Any, opts: BuildOptions,
                   measure_ids: list[str]) -> list[WikiPage]:
    """데이터가 말해 주는 것만 페이지로 만든다. 없으면 만들지 않는다."""
    out: list[WikiPage] = []

    over = [m for m in ex.measurements if m.fields["load_pct"] > 100]
    if over:
        body = [
            "# 정격 초과 운전 — 측정 부하율 100% 초과",
            "",
            "현장 계측에서 부하율이 정격을 넘는 설비가 확인됐다. 명판 용량으로 연간 "
            "사용량을 추정하면 **실제보다 적게** 나온다.",
            "",
            _md_table(["기번", "평균 전력(kW)", "부하율(%)"],
                      [[m.fields["tag"], _num(m.fields["avg_kw"], 1),
                        _num(m.fields["load_pct"])] for m in over]),
            "",
            "## 왜 중요한가",
            "",
            "- 정격 기준 추정은 절감량을 과소평가한다 — 개선 효과가 실제보다 작아 보인다.",
            "- 정격 초과는 노후·과부하의 직접 증거이므로 개체 사업의 근거가 된다.",
            "",
            f"> 사례 1건에서 나온 관찰이다. 일반화는 {REVIEW_MARK}",
            "",
            "## 관련",
            "",
            " · ".join(page_mod.link(m) for m in measure_ids) or "—",
        ]
        out.append(page_mod.build(
            stable_id="cpt-load-factor-over-rated", page_type="concept",
            title="정격 초과 운전 (부하율 100% 초과)", body="\n".join(body),
            source_span=[_span(doc, [m.span.pages[0] for m in over], "현장 계측")],
            acl=ACL_BY_TYPE["concept"], numeric_verified=True,
            measurement_basis="measured", confidence="high",
            tags=["인사이트", "계측"], related=list(measure_ids), **_fm(opts)))

    elec = _agg(ex, "전기", "에너지량")
    fuel = _agg(ex, "LPG", "에너지량")
    if elec and fuel and elec["before"] > elec["after"] and fuel["after"] > fuel["before"]:
        body = [
            "# 연료 전환형 개선 — 전력은 줄고 연료는 는다",
            "",
            "전기 구동 설비를 열원 설비로 바꾸는 개선안은 전력 사용량을 크게 줄이지만 "
            "**연료 사용량은 늘린다.** 전력 절감만 보고 판단하면 회수기간을 낙관하게 된다.",
            "",
            _md_table(["구분", "개선전(toe)", "개선후(toe)", "증감(toe)"], [
                ["전기", _num(elec["before"], 2), _num(elec["after"], 2),
                 _num(elec["after"] - elec["before"], 2)],
                ["연료", _num(fuel["before"], 2), _num(fuel["after"], 2),
                 _num(fuel["after"] - fuel["before"], 2)],
            ]),
            "",
            "## 판단에 필요한 것",
            "",
            "- 전력 단가와 연료 단가의 **비율**이 회수기간을 좌우한다.",
            "- 연료 단가는 계약 형태(탱크로리·배관)에 따라 크게 달라진다.",
            f"- 단가가 개정되면 결론이 바뀐다 → {page_mod.link('reg-energy-unit-price')}",
            "",
            f"> 사례 1건에서 나온 관찰이다. 일반화는 {REVIEW_MARK}",
            "",
            "## 관련",
            "",
            " · ".join(page_mod.link(m) for m in measure_ids) or "—",
        ]
        out.append(page_mod.build(
            stable_id="cpt-fuel-switch-tradeoff", page_type="concept",
            title="연료 전환형 개선의 상충 구조", body="\n".join(body),
            source_span=[_span(doc, [31], "사업 전·후 집계표")],
            acl=ACL_BY_TYPE["concept"], numeric_verified=_checks_for(ex.checks, "에너지량")[0],
            measurement_basis="mixed", confidence="medium",
            tags=["인사이트", "경제성"],
            related=[*measure_ids, "reg-energy-unit-price"], **_fm(opts)))
    return out


def _agg(ex: Any, group: str, item: str) -> dict[str, Any] | None:
    for f in ex.aggregate:
        if f.fields["group"].replace(" ", "") == group and item in f.fields["item"]:
            return f.fields
    return None
