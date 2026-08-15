"""LLMWiki CLI."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .docgen import generate_all
from .indexer import load_index, save_index, scan

app = typer.Typer(help="레거시 소스 → AI 분석 → 산출물(MD) → 위키 뷰어", no_args_is_help=True)
console = Console()

ConfigOpt = typer.Option("config.yaml", "--config", "-c", help="설정 파일 경로")


@app.command()
def parse(config: str = ConfigOpt):
    """소스를 정적 분석해 index.json 을 만든다."""
    cfg = load_config(config)
    console.print(f"[bold]{cfg.project_name}[/] 분석 중…")
    idx = scan(cfg)
    path = save_index(cfg, idx)

    table = Table(title="분석 결과", show_header=True)
    table.add_column("항목")
    table.add_column("건수", justify="right")
    table.add_row("클래스", str(len(idx.classes)))
    table.add_row("Mapper XML", str(len(idx.mappers)))
    table.add_row("SQL 문", str(len(idx.statements)))
    table.add_row("테이블", str(len(idx.tables)))
    table.add_row("호출 엣지", str(len(idx.edges)))
    table.add_row("프로그램(산출물 단위)", str(len(idx.programs)))
    console.print(table)
    console.print(f"인덱스 저장: [green]{path}[/]")


@app.command()
def programs(config: str = ConfigOpt):
    """추출된 프로그램 목록을 본다."""
    cfg = load_config(config)
    idx = load_index(cfg, with_source=False)
    table = Table(show_header=True)
    table.add_column("ID")
    table.add_column("업무명")
    table.add_column("계층")
    table.add_column("SQL", justify="right")
    table.add_column("테이블")
    for p in idx.programs:
        table.add_row(p.id, p.name, p.layer, str(len(p.sql_ids)), ", ".join(p.tables[:4]))
    console.print(table)


@app.command()
def generate(
    config: str = ConfigOpt,
    only: str = typer.Option(None, "--only", help="특정 프로그램 ID만 생성"),
    force: bool = typer.Option(False, "--force", "-f", help="변경 없어도 재생성"),
):
    """LLM 으로 프로그램 명세서(MD)를 생성한다."""
    cfg = load_config(config)
    idx = load_index(cfg)
    console.print(f"LLM provider: [bold]{cfg.provider}[/] ({cfg.llm_options.get('model')})")

    def progress(pid: str, status: str) -> None:
        color = {"generated": "green", "skipped": "dim"}.get(status, "red")
        console.print(f"  [{color}]{status:<10}[/] {pid}")

    result = generate_all(cfg, idx, only=only, force=force, on_progress=progress)
    console.print(
        f"\n생성 [green]{len(result['generated'])}[/] / "
        f"건너뜀 [dim]{len(result['skipped'])}[/] / "
        f"실패 [red]{len(result['failed'])}[/]"
    )
    for f in result["failed"]:
        console.print(f"  [red]{f['id']}[/]: {f['error']}")


@app.command()
def serve(
    config: str = ConfigOpt,
    host: str = typer.Option(None, help="바인드 호스트"),
    port: int = typer.Option(None, help="포트"),
    reload: bool = typer.Option(False, "--reload", help="개발용 자동 리로드"),
):
    """뷰어(위키) 서버를 띄운다."""
    import os

    import uvicorn

    cfg = load_config(config)
    os.environ["LLMWIKI_CONFIG"] = str(Path(config).resolve())
    console.print(
        f"[bold]{cfg.project_name}[/] 위키 → "
        f"http://{host or cfg.host}:{port or cfg.port}"
    )
    uvicorn.run(
        "llmwiki.server.app:app",
        host=host or cfg.host,
        port=port or cfg.port,
        reload=reload,
    )


@app.command()
def ontology(
    action: str = typer.Argument("validate", help="validate | export | show"),
    config: str = ConfigOpt,
    out: str = typer.Option(None, "--out", "-o", help="export 결과를 쓸 파일"),
    graph: bool = typer.Option(False, "--graph", help="export 시 스키마 대신 그래프를 내보낸다"),
):
    """온톨로지 스키마 검사 / 내보내기."""
    import json

    from .ontology import ONTOLOGY_VERSION, EDGE_TYPES, NODE_TYPES, build_graph, schema_dict
    from .ontology import validate_index

    cfg = load_config(config)

    if action == "show":
        console.print(f"온톨로지 v[bold]{ONTOLOGY_VERSION}[/]")
        t = Table(show_header=True, title="노드")
        t.add_column("타입"); t.add_column("ID 규칙"); t.add_column("근거"); t.add_column("설명")
        for n in NODE_TYPES.values():
            t.add_row(n.name, f"{n.prefix}:" + "/".join(f"{{{p}}}" for p in n.id_parts),
                      n.derivation, n.ko)
        console.print(t)
        e = Table(show_header=True, title="관계")
        e.add_column("관계"); e.add_column("도메인 → 레인지"); e.add_column("카디널리티"); e.add_column("근거")
        for x in EDGE_TYPES.values():
            e.add_row(x.name, f"{'|'.join(x.domain)} → {'|'.join(x.range)}",
                      x.cardinality, x.derivation)
        console.print(e)
        return

    if action == "export":
        payload = build_graph(load_index(cfg, with_source=False)) if graph else schema_dict()
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if out:
            Path(out).write_text(text, encoding="utf-8")
            console.print(f"저장: [green]{out}[/]")
        else:
            print(text)
        return

    if action != "validate":
        console.print(f"[red]알 수 없는 동작: {action}[/] (validate | export | show)")
        raise typer.Exit(code=2)

    result = validate_index(load_index(cfg, with_source=False))
    for issue in result.issues:
        color = "red" if issue.level == "error" else "yellow"
        console.print(f"  [{color}]{issue.level:<7}[/] {issue.code:<18} {issue.message}")
    if result.ok:
        console.print(
            f"온톨로지 v{ONTOLOGY_VERSION} [green]적합[/]"
            f" (경고 {len(result.warnings)}건)"
        )
    else:
        console.print(f"[red]오류 {len(result.errors)}건[/] / 경고 {len(result.warnings)}건")
        raise typer.Exit(code=1)


@app.command()
def pipeline(config: str = ConfigOpt, force: bool = typer.Option(False, "--force", "-f")):
    """parse → generate 를 한 번에 (CI/CD 배포 훅용)."""
    cfg = load_config(config)
    idx = scan(cfg)
    save_index(cfg, idx)
    console.print(f"분석 완료: 프로그램 {len(idx.programs)}건")
    result = generate_all(cfg, idx, force=force)
    console.print(
        f"산출물 생성 {len(result['generated'])} / 건너뜀 {len(result['skipped'])} / "
        f"실패 {len(result['failed'])}"
    )
    if result["failed"]:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
