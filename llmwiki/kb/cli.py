"""`llmwiki kb …` — 문서 4채널 분해 · 업종 분류 · 적재 게이트 CLI."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ..config import load_config
from . import classify, gate, ingest as kb_ingest, ontology, parse, taxonomy
from .store import Store

app = typer.Typer(help="문서 지식베이스 — 글·표·그림·엑셀 4채널 분해와 업종별 적재",
                  no_args_is_help=True)
console = Console()

ConfigOpt = typer.Option("config.yaml", "--config", "-c", help="설정 파일 경로")

SEVERITY_COLOR = {"blocker": "red", "error": "orange3", "warning": "yellow", "info": "cyan"}

#: AI기본법 제31조 — 이 CLI 는 아래 `_notice()` 로 사전 고지를 찍고 산출물 끝에 생성물
#: 표시를 남긴다. 그래서 점검에 그 사실을 알린다. 문구를 빼면 이 값도 함께 내려야 한다.
NOTICED = {"has_prior_notice": True, "has_output_labeling": True}

PRIOR_NOTICE = ("본 도구는 생성형 인공지능이 포함된 시스템의 일부다. 구조·수치 추출과 "
                "규제 검토는 결정론적 규칙이 수행하며, 최종 판단과 책임은 담당자에게 있다. "
                "(인공지능 기본법 제31조제1항)")
OUTPUT_MARK = ("이 결과는 생성형 인공지능이 포함된 시스템에서 만들어졌다. "
               "(인공지능 기본법 제31조제2항 생성물 표시)")


def _notice() -> None:
    console.print(f"[dim]{PRIOR_NOTICE}[/]")


def _store(config: str) -> tuple[Store, Any]:
    cfg = load_config(config)
    return Store(cfg.kb_dir), cfg


# --------------------------------------------------------------------------- #
@app.command()
def sectors(config: str = ConfigOpt):
    """업종 닫힌 집합과 업종별 필수지표를 본다."""
    load_config(config)  # 설정이 깨져 있으면 여기서 먼저 걸린다
    t = Table(show_header=True, title=f"업종 {len(taxonomy.SECTOR_CODES)}종 (닫힌 집합)")
    for col in ("코드", "업종", "KSIC", "원단위 분모", "필수지표", "주요 설비"):
        t.add_column(col)
    for p in taxonomy.SECTORS.values():
        t.add_row(p.code, p.name, p.ksic, p.unit_basis,
                  str(len(p.required_metrics)), ", ".join(p.key_equipment[:4]) or "—")
    console.print(t)


@app.command()
def schema(config: str = ConfigOpt, out: str = typer.Option(None, "--out", "-o")):
    """지식베이스 온톨로지 스키마를 본다 / 내보낸다."""
    load_config(config)
    if out:
        Path(out).write_text(
            json.dumps(ontology.schema_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"저장: [green]{out}[/]")
        return
    console.print(f"문서 지식베이스 온톨로지 v[bold]{ontology.KB_ONTOLOGY_VERSION}[/]")
    t = Table(show_header=True, title="노드")
    for col in ("타입", "ID 규칙", "근거", "스팬필수", "설명"):
        t.add_column(col)
    for n in ontology.NODE_TYPES.values():
        t.add_row(n.name, f"{n.prefix}:" + "/".join(f"{{{p}}}" for p in n.id_parts),
                  n.derivation, "●" if n.requires_span else "", n.ko)
    console.print(t)
    e = Table(show_header=True, title="관계")
    for col in ("관계", "도메인 → 레인지", "카디널리티", "근거"):
        e.add_column(col)
    for x in ontology.EDGE_TYPES.values():
        e.add_row(x.name, f"{'|'.join(x.domain)} → {'|'.join(x.range)}",
                  x.cardinality, x.derivation)
    console.print(e)


@app.command()
def analyze(
    pdf: str = typer.Argument(..., help="분석할 PDF 경로"),
    config: str = ConfigOpt,
    sector: str = typer.Option(None, "--sector", "-s", help="업종을 직접 지정 (미지정 시 규칙 분류)"),
    out: str = typer.Option(None, "--out", "-o", help="분석 결과 JSON 을 쓸 파일"),
    graph_out: str = typer.Option(None, "--graph", help="온톨로지 그래프 JSON 을 쓸 파일"),
    ttl_out: str = typer.Option(None, "--ttl", help="TTL 을 쓸 파일"),
    excel: bool = typer.Option(True, "--excel/--no-excel", help="엑셀 채널 생성"),
    excel_dir: str = typer.Option(None, "--excel-dir", help="엑셀 채널을 쓸 폴더 (기본: 임시 폴더)"),
):
    """PDF 를 4채널로 분해하고 분류·게이트·온톨로지까지 돌린다. **적재하지 않는다.**"""
    cfg = load_config(config)
    _notice()
    dest = gate.destination_for(cfg.kb_destination)
    console.print(f"목적지 [bold]{dest.name}[/] "
                  f"({'국외 이전 해당' if dest.cross_border else '국외 이전 비해당'})")
    try:
        # 원본이 있는 폴더에 산출물을 흘리지 않는다 — 남의 소스 폴더는 건드리지 않는다.
        res = kb_ingest.analyze(pdf, sector_override=sector, destination=dest,
                                build_excel=excel, out_dir=excel_dir or tempfile.gettempdir(),
                                lang=cfg.language, **NOTICED)
    except parse.ParseError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    _print_result(res)

    if out:
        payload = res.to_dict()
        payload["graph"] = res.graph
        Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"분석 결과: [green]{out}[/]")
    if graph_out and res.graph:
        Path(graph_out).write_text(
            json.dumps(res.graph, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"그래프: [green]{graph_out}[/]")
    if ttl_out and res.graph:
        Path(ttl_out).write_text(ontology.to_turtle(res.graph), encoding="utf-8")
        console.print(f"TTL: [green]{ttl_out}[/]")


@app.command()
def ingest(
    pdf: str = typer.Argument(..., help="적재할 PDF 경로"),
    config: str = ConfigOpt,
    sector: str = typer.Option(None, "--sector", "-s", help="업종을 직접 지정"),
    mask: bool = typer.Option(True, "--mask/--no-mask", help="비식별 처리 (끄면 잔존 시 거부된다)"),
):
    """분석 → 게이트 → 업종 구획 적재. 게이트를 우회하는 인자는 없다."""
    store, cfg = _store(config)
    _notice()
    dest = gate.destination_for(cfg.kb_destination)
    try:
        # 엑셀은 임시 폴더에 만들고, 적재가 성공하면 저장소가 사본을 갖는다.
        res = kb_ingest.analyze(pdf, sector_override=sector, destination=dest,
                                build_excel=True, out_dir=tempfile.gettempdir(),
                                lang=cfg.language, **NOTICED)
    except parse.ParseError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    _print_result(res)
    stored = store.ingest(res, mask=mask)
    if stored.get("stored"):
        console.print(
            f"적재 [green]{stored['stored']}건[/] → {stored['partition']} "
            f"({', '.join(f'{k} {v}' for k, v in stored['by_channel'].items())})"
        )
        console.print(f"경로: {stored['path']}")
    else:
        console.print(f"[yellow]적재하지 않았다[/] — {stored.get('skipped', '이유 미기록')}")
        raise typer.Exit(code=1)


@app.command()
def documents(config: str = ConfigOpt,
              sector: str = typer.Option(None, "--sector", "-s", help="업종으로 필터")):
    """적재된 문서 목록."""
    store, _ = _store(config)
    rows = store.documents(sector)
    if not rows:
        console.print("[dim]적재된 문서가 없다. `llmwiki kb ingest <pdf>` 로 넣는다.[/]")
        return
    t = Table(show_header=True)
    for col in ("문서해시", "파일", "업종", "채널레코드", "비식별", "판정", "적재시각"):
        t.add_column(col)
    for r in rows:
        t.add_row(r["doc_hash"], r.get("filename", ""), r.get("sector_name", ""),
                  str(r.get("stored", 0)), "●" if r.get("masked") else "",
                  r.get("verdict", ""), r.get("ingested_at", ""))
    console.print(t)
    console.print(json.dumps(store.stats(), ensure_ascii=False))


@app.command()
def search(
    query: str = typer.Argument(..., help="검색어"),
    config: str = ConfigOpt,
    sector: str = typer.Option(None, "--sector", "-s", help="업종 필터"),
    channel: str = typer.Option(None, "--channel", help=f"채널 필터 {parse.CHANNELS}"),
    limit: int = typer.Option(10, "--limit", "-n"),
):
    """적재된 채널을 검색한다."""
    store, _ = _store(config)
    hits = store.search(query, sector=sector, channel=channel, limit=limit)
    if not hits:
        console.print("[dim]결과가 없다.[/]")
        return
    for h in hits:
        console.print(
            f"[bold]{h['sector_name']}[/] · {h['channel']} · p.{h['page']} "
            f"[dim]{h['anchor']} ({h['filename']})[/] score={h['score']}"
        )
        console.print(f"  {h['snippet']}\n")


@app.command()
def validate(config: str = ConfigOpt):
    """적재된 모든 그래프가 온톨로지를 지키는지 검사한다."""
    store, _ = _store(config)
    rows = store.documents()
    if not rows:
        console.print("[dim]검사할 그래프가 없다.[/]")
        return
    bad = 0
    for r in rows:
        graph = store.graph(r["doc_hash"])
        if graph is None:
            console.print(f"[yellow]그래프 없음[/] {r['doc_hash']}")
            continue
        result = ontology.validate_graph(graph)
        for issue in result.issues:
            color = "red" if issue.level == "error" else "yellow"
            console.print(f"  [{color}]{issue.level:<7}[/] {issue.code:<24} {issue.message}")
        mark = "[green]적합[/]" if result.ok else "[red]부적합[/]"
        console.print(f"{mark} {r['doc_hash']} ({r.get('filename', '')}) "
                      f"— 오류 {len(result.errors)} / 경고 {len(result.warnings)}")
        bad += 0 if result.ok else 1
    if bad:
        raise typer.Exit(code=1)


@app.command()
def review(
    text_file: str = typer.Argument(..., help="검토할 텍스트 파일 (.txt/.md)"),
    config: str = ConfigOpt,
    mask: bool = typer.Option(False, "--mask", help="비식별 처리 결과를 함께 낸다"),
):
    """텍스트 하나에 개인정보·AI기본법 룰만 돌려 본다 (PDF 없이 규칙 확인용)."""
    cfg = load_config(config)
    text = Path(text_file).read_text(encoding="utf-8")
    dest = gate.destination_for(cfg.kb_destination)
    report = gate.review(text, destination=dest, lang=cfg.language)
    console.print(f"판정 [bold]{report['verdict_label']}[/] · 개인정보 {report['pii_detected']}건 "
                  f"· 목적지 {dest.name}")
    _print_findings(report["findings"])
    if mask:
        v = gate.verify_masking(text)
        console.print(f"\n치환 {v['masked_count']}건 / 잔존 {v['residual_count']}건 "
                      f"({'검산 통과' if v['clean'] else '검산 실패 — 적재 불가'})")


# --------------------------------------------------------------------------- #
def _print_result(res) -> None:
    s = res.parse_summary
    t = Table(show_header=True, title=f"{res.filename} ({res.doc_hash})")
    t.add_column("항목")
    t.add_column("값", justify="right")
    t.add_row("면수", str(s.get("pages", 0)))
    t.add_row("글 블록", f"{s.get('text_blocks', 0)} ({s.get('text_chars', 0):,}자)")
    t.add_row("표", f"{s.get('tables', 0)} ({s.get('table_rows', 0)}행, "
                    f"숫자셀 {s.get('numeric_cells', 0)})")
    t.add_row("그림", str(s.get("images", 0)))
    console.print(t)

    cls = res.classification
    mark = "[yellow]검토 필요[/]" if res.needs_review else "[green]확정[/]"
    console.print(f"업종 [bold]{res.sector_name}[/] {mark} "
                  f"(신뢰도 {cls.get('confidence', 0):.0%}, {cls.get('method')}) → {res.partition}")
    console.print(f"  {cls.get('reason', '')}")

    cov = res.coverage
    console.print(f"필수지표 {len(cov.get('present', []))}/{cov.get('required', 0)} "
                  f"({cov.get('coverage', 0):.0%}) · 원단위 {cov.get('unit_basis', '')}")
    for m in cov.get("missing", []):
        console.print(f"  [yellow]누락[/] {m['label']}")

    console.print(f"게이트 [bold]{res.gate.get('verdict_label', '')}[/] · "
                  f"개인정보 {res.gate.get('pii_detected', 0)}건 탐지, "
                  f"{res.masking.get('masked_count', 0)}건 치환, "
                  f"잔존 {res.masking.get('residual_count', 0)}건")
    console.print(f"  원문 적재 {'가능' if res.upload_allowed_raw else '불가'} · "
                  f"비식별 후 적재 {'가능' if res.upload_allowed else '불가'}")
    _print_findings(res.gate.get("findings", []))

    g = res.graph_stats
    console.print(f"온톨로지 노드 {g.get('nodes', 0)} · 엣지 {g.get('edges', 0)} · "
                  f"수치 {g.get('quantities', 0)} · 지적 {g.get('findings', 0)}")
    v = res.validation
    if not v.get("ok", True):
        console.print(f"[red]스키마 오류 {v.get('errors')}건[/]")
        for issue in v.get("issues", []):
            console.print(f"  [red]{issue['code']}[/] {issue['message']}")
    for warn in s.get("warnings", []):
        console.print(f"[yellow]⚠[/] {warn}")
    for err in res.errors:
        console.print(f"[red]✕[/] {err}")
    if res.excel_path:
        console.print(f"엑셀 채널: {res.excel_path}")
    console.print(f"[dim]{OUTPUT_MARK}[/]")


def _print_findings(findings: list[dict]) -> None:
    for f in findings:
        color = SEVERITY_COLOR.get(f["severity"], "white")
        console.print(f"  [{color}]{f['severity']:<8}[/] {f['title']}  "
                      f"[dim]{f['law']} {f['article']}[/]")
