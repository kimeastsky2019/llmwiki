"""`llmwiki wiki …` — 에너지 진단 위키의 3연산(ingest · query · lint) CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ..config import load_config
from ..kb import ingest as kb_ingest, gate, parse
from . import assist as assist_mod, build as build_mod, calc, contract
from . import lint as lint_mod, retrieval, review, route
from . import units as units_mod
from .store import WikiStore, write_all

app = typer.Typer(help="에너지 진단 위키 — 데이터 컨트랙트가 걸린 마크다운 지식베이스",
                  no_args_is_help=True)
console = Console()

ConfigOpt = typer.Option("config.yaml", "--config", "-c", help="설정 파일 경로")

SEVERITY_COLOR = {"blocker": "red", "error": "orange3", "warning": "yellow", "info": "cyan"}

PRIOR_NOTICE = ("본 도구는 생성형 인공지능이 포함된 시스템의 일부다. 수치는 LLM 이 "
                "생성하지 않으며 파싱·계산·검산은 결정론적 코드가 수행한다. 최종 판단과 "
                "책임은 담당자에게 있다. (인공지능 기본법 제31조제1항)")


def _store(config: str) -> tuple[WikiStore, Any]:
    cfg = load_config(config)
    return WikiStore(cfg.wiki_dir), cfg


# --------------------------------------------------------------------------- #
# ingest
# --------------------------------------------------------------------------- #
@app.command()
def ingest(
    pdf: str = typer.Argument(..., help="진단 보고서 PDF"),
    site: str = typer.Option("", "--site", "-s",
                             help="사업장 키 (ASCII). 지정하지 않으면 문서 해시를 쓴다"),
    sector: str = typer.Option(None, "--sector", help="업종 코드 (kb 택소노미)"),
    owner: str = typer.Option("energy-team", "--owner"),
    dry_run: bool = typer.Option(False, "--dry-run", help="생성만 하고 저장하지 않는다"),
    config: str = ConfigOpt,
):
    """PDF → 위키 페이지. 게이트를 통과한 문서만 페이지가 된다."""
    console.print(f"[dim]{PRIOR_NOTICE}[/]")
    st, cfg = _store(config)
    doc = parse.parse_pdf(pdf, extract_images=False)

    analysis = kb_ingest.analyze(
        pdf, sector_override=sector, destination=gate.destination_for(cfg.kb_destination),
        build_excel=False, has_prior_notice=True, has_output_labeling=True)
    if not analysis.upload_allowed:
        console.print("[red]적재 게이트가 막았다[/] — 위키를 만들지 않는다")
        for f in analysis.gate.get("findings", [])[:5]:
            console.print(f"  [{f.get('severity')}] {f.get('title')}")
        raise typer.Exit(1)

    res = build_mod.build(
        doc, options=build_mod.BuildOptions(site_key=site, owner=owner,
                                            pipeline_version=cfg.wiki_pipeline_version),
        analysis=analysis.to_dict())

    t = Table(show_header=True, title=f"생성된 페이지 {len(res.pages)}건")
    for col in ("타입", "stable_id", "ACL", "검산", "제목"):
        t.add_column(col)
    for p in res.pages:
        t.add_row(p.type, p.stable_id, p.acl,
                  "[green]OK[/]" if p.numeric_verified else "[yellow]미검산[/]", p.title)
    console.print(t)
    for w in res.warnings:
        console.print(f"[yellow]![/] {w}")

    if dry_run:
        console.print("[dim]--dry-run 이라 저장하지 않았다[/]")
        return
    write_all(st, res.pages, actor=owner, note=f"ingest {Path(pdf).name}")
    console.print(f"저장: [green]{st.root}[/] · 카탈로그 {st.index_path.name} 갱신")
    _lint_summary(lint_mod.run(st))


# --------------------------------------------------------------------------- #
# query
# --------------------------------------------------------------------------- #
@app.command()
def search(
    query: str = typer.Argument(...),
    acl: str = typer.Option("internal", "--acl", help="이 등급까지만 본다"),
    type_: str = typer.Option(None, "--type", "-t", help="페이지 타입 필터"),
    limit: int = typer.Option(10, "--limit", "-n"),
    config: str = ConfigOpt,
):
    """BM25 ⊕ n-그램 → RRF 하이브리드 검색. ACL 필터를 코드가 건다."""
    st, _ = _store(config)
    idx = retrieval.Index(st.pages())
    hits = idx.search(query, limit=limit, acl_max=acl, page_type=type_)
    t = Table(show_header=True, title=f"검색 결과 {len(hits)}건 (acl ≤ {acl})")
    for col in ("점수", "타입", "stable_id", "상태", "검산", "발췌"):
        t.add_column(col)
    for h in hits:
        t.add_row(f"{h.score:.4f}", h.type, h.stable_id, h.status,
                  "OK" if h.numeric_verified else "미검산", h.snippet[:60])
    console.print(t)


@app.command()
def pages(type_: str = typer.Option(None, "--type", "-t"),
          status: str = typer.Option(None, "--status"), config: str = ConfigOpt):
    """페이지 목록."""
    st, _ = _store(config)
    rows = st.pages(page_type=type_, status=status)
    t = Table(show_header=True, title=f"페이지 {len(rows)}건")
    for col in ("타입", "stable_id", "v", "상태", "ACL", "검산", "제목"):
        t.add_column(col)
    for p in rows:
        t.add_row(p.type, p.stable_id, str(p.version), p.status, p.acl,
                  "OK" if p.numeric_verified else "미검산", p.title)
    console.print(t)
    console.print(st.stats())


@app.command()
def show(stable_id: str = typer.Argument(...), config: str = ConfigOpt):
    """페이지 원문(front-matter 포함)을 본다."""
    st, _ = _store(config)
    p = st.read(stable_id)
    if p is None:
        console.print(f"[red]페이지가 없다: {stable_id}[/]")
        raise typer.Exit(1)
    console.print(p.dumps())
    back = st.backlinks(stable_id)
    if back:
        console.print(f"[dim]역링크: {', '.join(back)}[/]")


@app.command()
def index(config: str = ConfigOpt):
    """카탈로그(index.md)를 다시 만든다. 위키가 원본이고 이건 산출물이다 (P1)."""
    st, _ = _store(config)
    console.print(f"재생성: [green]{st.rebuild_index()}[/]")


# --------------------------------------------------------------------------- #
# lint
# --------------------------------------------------------------------------- #
@app.command()
def lint(fail_on: str = typer.Option("error", "--fail-on",
                                     help="이 심각도 이상이면 종료코드 1 (blocker|error|warning)"),
         json_out: bool = typer.Option(False, "--json"), config: str = ConfigOpt):
    """무결성 검사. 주 1회 정기 배치로 돌린다 (P4)."""
    st, _ = _store(config)
    res = lint_mod.run(st)
    if json_out:
        console.print_json(json.dumps(res.to_dict(), ensure_ascii=False))
    else:
        _lint_summary(res, detail=True)
    order = list(lint_mod.SEVERITIES)
    threshold = order.index(fail_on) if fail_on in order else 1
    if any(order.index(f.severity) <= threshold for f in res.findings):
        raise typer.Exit(1)


def _lint_summary(res: lint_mod.LintResult, detail: bool = False) -> None:
    d = res.to_dict()
    console.print(
        f"lint: 페이지 {d['pages']}건 · "
        + " · ".join(f"[{SEVERITY_COLOR.get(s,'white')}]{s} {n}[/]"
                     for s, n in d["counts"].items())
        + (" · [green]배포 가능[/]" if res.deployable else " · [red]배포 차단[/]"))
    if not detail:
        return
    t = Table(show_header=True)
    for col in ("심각도", "코드", "페이지", "내용"):
        t.add_column(col)
    for f in res.findings:
        if f.severity == "info":
            continue
        t.add_row(f"[{SEVERITY_COLOR.get(f.severity,'white')}]{f.severity}[/]",
                  f.code, f.page, f.message[:80])
    console.print(t)


# --------------------------------------------------------------------------- #
# 검증
# --------------------------------------------------------------------------- #
@app.command()
def queue(limit: int = typer.Option(20, "--limit", "-n"), config: str = ConfigOpt):
    """검토 큐. 검토하지 않으면 무엇이 잘못되는가 순으로 정렬된다."""
    st, _ = _store(config)
    items = review.queue(st)
    t = Table(show_header=True, title=f"검토 대기 {len(items)}건")
    for col in ("우선", "타입", "stable_id", "상태", "검산", "사유"):
        t.add_column(col)
    for i in items[:limit]:
        t.add_row(str(i.priority), i.type, i.stable_id, i.status,
                  "OK" if i.numeric_verified else "미검산", ", ".join(i.reasons))
    console.print(t)


@app.command()
def verify(
    stable_id: str = typer.Argument(...),
    actor: str = typer.Option(..., "--actor", "-a", help="검토자 (서명)"),
    decision: str = typer.Option("approve", "--decision", "-d",
                                 help="approve | reject | deprecate"),
    note: str = typer.Option("", "--note"),
    ack: bool = typer.Option(False, "--ack-unverified",
                             help="검산 미통과를 인지하고 승인한다"),
    config: str = ConfigOpt,
):
    """검토 결정을 기록한다. 서명 없이는 확정되지 않는다."""
    st, _ = _store(config)
    try:
        rec = review.decide(st, stable_id, decision, actor=actor, note=note,
                            acknowledge_unverified=ack)
    except review.ReviewError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[green]{decision}[/] {stable_id} → {rec['status']} (검토자 {actor})")


@app.command()
def journal(limit: int = typer.Option(20, "--limit", "-n"), config: str = ConfigOpt):
    """검증 저널. 덧붙이기뿐이라 지워지지 않는다."""
    st, _ = _store(config)
    t = Table(show_header=True, title="검증 저널")
    for col in ("시각", "결정", "페이지", "v", "검토자", "미검산 인지", "비고"):
        t.add_column(col)
    for r in review.journal(st, limit=limit):
        t.add_row(r["at"], r["decision"], r["stable_id"], str(r["version"]), r["actor"],
                  "●" if r.get("acknowledged_unverified") else "", r.get("note", ""))
    console.print(t)


@app.command()
def reanalyze(
    stable_id: str = typer.Argument(..., help="다시 쓸 페이지"),
    provider: str = typer.Option("", "--provider", "-p",
                                 help="internal | external | 공급자 이름 (기본: 사내)"),
    apply: bool = typer.Option(False, "--apply", help="결과를 페이지에 반영한다"),
    actor: str = typer.Option("", "--actor", "-a", help="반영할 때의 서명"),
    config: str = ConfigOpt,
):
    """페이지 하나를 **원문 발췌를 근거로** 다시 쓴다.

    규칙이 만든 페이지는 문장이 거칠고 맥락이 빠져 있다. 재분석은 그 페이지가 인용한
    쪽의 원문을 함께 넣어 서술을 고친다 — 표와 수치는 그대로 두고. 반영은 `--apply`
    를 줄 때만 하고, 그때도 서명이 필요하다.
    """
    from ..kb.store import Store as KbStore

    st, cfg = _store(config)
    page = st.read(stable_id)
    if page is None:
        console.print(f"[red]페이지가 없다: {stable_id}[/]")
        raise typer.Exit(1)

    kb = KbStore(cfg.kb_dir)
    chunks: list = []
    docs = {str(span.get("doc", "")) for span in page.source_span}
    for record in kb.documents():
        if record.get("filename") in docs:
            chunks = kb.channels(record["doc_hash"])
            break

    try:
        result = assist_mod.reanalyze(page, cfg=cfg, chunks=chunks, provider=provider)
    except assist_mod.AssistError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    console.print(f"경로: [bold]{result.provider}[/] (요청 {result.requested}) · "
                  f"원문 발췌 {len(assist_mod.source_excerpt(page, chunks)):,}자")
    for w in result.warnings:
        console.print(f"[yellow]![/] {w}")
    console.print(result.text)

    if not apply:
        console.print("[dim]--apply 를 주면 반영한다 (서명 필요)[/]")
        return
    if not actor.strip():
        console.print("[red]서명 없이 반영할 수 없다 — --actor 를 준다[/]")
        raise typer.Exit(1)
    if result.invented_numbers:
        console.print(f"[red]원문에 없는 수가 있다: {', '.join(result.invented_numbers[:8])} "
                      "— 반영하지 않는다[/]")
        raise typer.Exit(1)
    if not result.decision.get("structure_kept", True):
        console.print("[red]절 구조가 유지되지 않았다 — 반영하지 않는다[/]")
        raise typer.Exit(1)

    page.body = result.text
    record = st.write(page, actor=actor, note="재분석 결과 반영 (CLI)")
    st.rebuild_index()
    console.print(f"[green]반영[/] {stable_id} v{record['version']} · 상태 {record['status']}")


# --------------------------------------------------------------------------- #
# 스키마 · 단위 · 라우팅
# --------------------------------------------------------------------------- #
@app.command()
def schema(config: str = ConfigOpt):
    """데이터 컨트랙트의 닫힌 집합을 본다."""
    load_config(config)
    d = contract.schema_dict()
    t = Table(show_header=True, title=f"데이터 컨트랙트 v{d['contract_version']}")
    for col in ("타입", "접두사", "디렉터리", "설명"):
        t.add_column(col)
    for row in d["types"]:
        t.add_row(row["name"], row["prefix"], row["directory"], row["note"] or row["ko"])
    console.print(t)
    console.print(f"ACL: {' < '.join(d['acl_levels'])} "
                  f"(외부 금지: {', '.join(d['acl_internal_only'])})")
    console.print(f"상태: {', '.join(d['statuses'])} · "
                  f"측정근거: {', '.join(d['measurement_bases'])}")
    console.print(f"필수 필드: {', '.join(d['required_fields'])}")


@app.command()
def units(config: str = ConfigOpt):
    """단위 환산 SSOT. 계수는 코드가 아니라 여기에만 있다."""
    load_config(config)
    table = units_mod.load()
    t = Table(show_header=True, title=f"단위 테이블 v{table.version} (기준 {table.standard})")
    for col in ("코드", "값", "단위", "유효 종료", "남은 일수", "근거"):
        t.add_column(col)
    for f in table.factors:
        days = f.expires_in()
        t.add_row(f.code, f"{f.value:g}", f.unit, f.valid_until,
                  "" if days is None else (f"[yellow]{days}[/]" if days <= 90 else str(days)),
                  f.source)
    console.print(t)


@app.command()
def routing(task: str = typer.Option(None, "--task"), acl: str = typer.Option(None, "--acl"),
            config: str = ConfigOpt):
    """모델 라우팅 정책. ACL 이 1순위, 난이도가 2순위다."""
    load_config(config)
    if task and acl:
        d = route.decide(task, acl)
        console.print(f"{task} · acl={acl} → [bold]{d.provider}[/] "
                      f"(tier={d.tier}, 외부허용={d.external_allowed})")
        console.print(f"[dim]{d.reason}[/]")
        return
    p = route.policy()
    t = Table(show_header=True, title="태스크별 기본 배정")
    for col in ("태스크", "티어", "public/internal", "confidential 이상"):
        t.add_column(col)
    for name in p["tasks"]:
        low, high = route.decide(name, "internal"), route.decide(name, "confidential")
        t.add_row(name, low.tier, low.provider, high.provider)
    console.print(t)


@app.command("calc")
def calc_cmd(
    kw: float = typer.Option(None, "--kw", help="전력(kW)"),
    hours: float = typer.Option(None, "--hours", help="연간 가동시간(h/y)"),
    load: float = typer.Option(100.0, "--load", help="부하율(%)"),
    count: int = typer.Option(1, "--count", help="대수"),
    investment: float = typer.Option(None, "--investment", help="투자비(천원)"),
    saving: float = typer.Option(None, "--saving", help="연간 절감금액(천원)"),
    config: str = ConfigOpt,
):
    """수치 계산기. 위키에 적히는 값과 **같은 함수**를 쓴다."""
    load_config(config)
    if kw and hours:
        kwh = calc.annual_kwh(kw, hours, load / 100.0, count)
        t = Table(show_header=True, title="연간 전력")
        for col in ("항목", "값", "단위"):
            t.add_column(col)
        t.add_row("연간 사용량", f"{kwh:,.0f}", "kWh/y")
        t.add_row("환산 에너지", f"{calc.toe_from_kwh(kwh):,.2f}", "toe/y")
        t.add_row("온실가스", f"{calc.tco2eq_from_kwh(kwh):,.2f}", "tCO2eq/y")
        t.add_row("사용금액", f"{calc.elec_cost_kwon(kwh):,.0f}", "천원/y")
        console.print(t)
    if investment and saving:
        console.print(f"회수기간: [bold]{calc.payback_years(investment, saving):.2f}[/] 년")
    if not (kw or investment):
        console.print("계산할 입력이 없다. --kw/--hours 또는 --investment/--saving 을 준다")
