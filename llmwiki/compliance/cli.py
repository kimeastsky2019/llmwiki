"""`llmwiki reg …` — 규제 지식그래프와 판정 엔진 CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from ..config import load_config
from . import analysis, changeset as cs, propose, rules, verify
from .ontology import COMPLIANCE_ONTOLOGY_VERSION, EDGE_TYPES, NODE_TYPES, VERDICT_LABELS
from .ontology import DEFERRAL_TRIGGERS, schema_dict
from .seed import RULESET_VERSION, seed as seed_demo
from .store import Store

app = typer.Typer(help="규제 지식그래프 · 근거기반 자동평가", no_args_is_help=True)
console = Console()

ConfigOpt = typer.Option("config.yaml", "--config", "-c", help="설정 파일 경로")

VERDICT_COLOR = {
    "SATISFIED": "green", "PARTIAL": "yellow", "UNSATISFIED": "red",
    "NOT_APPLICABLE": "dim", "DEFERRED": "cyan",
}


def _store(config: str) -> tuple[Store, Any]:
    cfg = load_config(config)
    return Store(cfg.compliance_dir), cfg


# --------------------------------------------------------------------------- #
@app.command()
def schema(config: str = ConfigOpt, out: str = typer.Option(None, "--out", "-o")):
    """규제 온톨로지 스키마를 본다 / 내보낸다."""
    if out:
        Path(out).write_text(
            json.dumps(schema_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"저장: [green]{out}[/]")
        return
    console.print(f"규제 온톨로지 v[bold]{COMPLIANCE_ONTOLOGY_VERSION}[/]")
    t = Table(show_header=True, title="노드")
    for col in ("타입", "ID 규칙", "근거", "앵커", "스팬필수", "sLM제안"):
        t.add_column(col)
    for n in NODE_TYPES.values():
        t.add_row(
            n.name, f"{n.prefix}:" + "/".join(f"{{{p}}}" for p in n.id_parts),
            n.derivation, "●" if n.anchor else "", "●" if n.requires_span else "",
            "" if n.llm_proposable else "[red]✕[/]",
        )
    console.print(t)
    e = Table(show_header=True, title="관계")
    for col in ("관계", "도메인 → 레인지", "카디널리티", "근거", "스팬필수"):
        e.add_column(col)
    for x in EDGE_TYPES.values():
        e.add_row(x.name, f"{'|'.join(x.domain)} → {'|'.join(x.range)}",
                  x.cardinality, x.derivation, "●" if x.requires_span else "")
    console.print(e)

    d = Table(show_header=True, title="판단 유보 트리거")
    d.add_column("코드"); d.add_column("사유")
    for code, note in DEFERRAL_TRIGGERS.items():
        d.add_row(code, note)
    console.print(d)


@app.command()
def seed(config: str = ConfigOpt,
         force: bool = typer.Option(False, "--force", "-f", help="기존 저널이 있어도 진행")):
    """데모 데이터를 커밋 결재 경로로 적재한다."""
    store, _ = _store(config)
    if store.journal_path.exists() and not force:
        console.print(
            f"[yellow]이미 저널이 있다:[/] {store.journal_path}\n"
            "append-only 라 시드를 다시 넣으면 이력이 겹친다. "
            "그래도 하려면 --force, 처음부터라면 디렉터리를 옮겨라."
        )
        raise typer.Exit(code=1)
    result = seed_demo(store)
    for line in result["log"]:
        console.print(f"  {line}")
    console.print(f"\n적재 완료: [green]{store.root}[/]")
    console.print("  " + " · ".join(f"{k} {v}" for k, v in result["counts"].items()))


@app.command()
def graph(config: str = ConfigOpt,
          as_of: str = typer.Option(None, "--as-of", help="이 시각의 승인 그래프로 되돌린다")):
    """승인 그래프 요약."""
    store, _ = _store(config)
    g = store.approved(as_of=as_of)
    over = analysis.overview(g)
    console.print(f"승인 그래프 (버전 {g.version or '—'})")
    t = Table(show_header=True)
    t.add_column("노드 타입"); t.add_column("건수", justify="right")
    for k, v in over["counts"].items():
        t.add_row(k, str(v))
    console.print(t)
    console.print(f"활성 엣지 {len(g.active_edges())} 건 / 제안 대기 {len(store.pending())} 건")


@app.command()
def validate(config: str = ConfigOpt):
    """승인 그래프가 스키마와 헌법 셋을 지키는지 검사한다."""
    store, _ = _store(config)
    g = store.approved()
    result = verify.validate_graph(g, documents=store.documents())
    journal = verify.validate_journal(store)
    for issue in result.issues + journal.issues:
        color = "red" if issue.level == "error" else "yellow"
        console.print(f"  [{color}]{issue.level:<7}[/] {issue.code:<22} {issue.message}")
    errors = len(result.errors) + len(journal.errors)
    if errors:
        console.print(f"[red]오류 {errors}건[/] / 경고 {len(result.warnings)}건")
        raise typer.Exit(code=1)
    console.print(
        f"규제 온톨로지 v{COMPLIANCE_ONTOLOGY_VERSION} [green]적합[/]"
        f" (경고 {len(result.warnings)}건)"
    )


@app.command()
def assess(
    config: str = ConfigOpt,
    service: str = typer.Option(None, "--service", "-s", help="특정 서비스만"),
    commit: bool = typer.Option(False, "--commit", help="판정을 그래프에 남긴다"),
    today: str = typer.Option(None, "--today", help="기준일 (YYYY-MM-DD)"),
):
    """판정한다 — 승인 그래프 위의 결정론적 룰. LLM 을 호출하지 않는다."""
    store, cfg = _store(config)
    g = store.approved()
    prior = _prior_verdicts(g)
    results = rules.adjudicate_all(
        g, service_uuid=service, ruleset_version=cfg.ruleset_version,
        standard_version=cfg.standard_version, metrics=store.metrics,
        today=today, prior=prior,
    )
    t = Table(show_header=True)
    for col in ("서비스", "통제", "판정", "룰 결과", "근거"):
        t.add_column(col)
    for a in results:
        name = g.props(f"svc:{a.service_uuid}").get("name", a.service_uuid)
        color = VERDICT_COLOR[a.verdict]
        t.add_row(
            str(name), a.control_code, f"[{color}]{a.label}[/]",
            VERDICT_LABELS[a.raw_verdict],
            a.reason if not a.triggers else a.reason + f"  [dim]({', '.join(a.triggers)})[/]",
        )
    console.print(t)
    m = verify.audit_metrics(results)
    console.print(
        f"자동 판정 [green]{m['decided']}[/] / 판단유보 [cyan]{m['deferred']}[/] "
        f"/ 전체 {m['total']}  (자동 처리율 {m['auto_rate']:.0%})"
    )
    if m["by_trigger"]:
        console.print("  유보 사유: " + ", ".join(f"{k} {v}" for k, v in m["by_trigger"].items()))
    if commit:
        n = rules.commit(store, results, ruleset_version=cfg.ruleset_version)
        console.print(f"판정 {len(results)}건을 그래프에 기록 (레코드 {n})")


@app.command()
def confirm(
    assessment: str = typer.Argument(..., help="판정 uuid"),
    by: str = typer.Option(..., "--by", help="확정 서명자 agent_id"),
    verdict: str = typer.Option(None, "--verdict", help="사람이 값을 바꿀 때"),
    note: str = typer.Option("", "--note"),
    config: str = ConfigOpt,
):
    """확정 서명 (게이트 3) — 자동 판정도 이 서명 전에는 잠정이다."""
    store, _ = _store(config)
    props = rules.confirm(store, assessment, agent_id=by, verdict=verdict, note=note)
    console.print(
        f"[green]확정[/] {props['control_code']} / {props['service_uuid']} → "
        f"{VERDICT_LABELS[props['verdict']]} (by {by})"
    )


@app.command()
def coverage(config: str = ConfigOpt, out: str = typer.Option(None, "--out", "-o")):
    """커버리지 갭 — 통제하지 않고 있는 규제 의무를 찾는다."""
    store, _ = _store(config)
    gap = analysis.coverage_gap(store.approved())
    if out:
        Path(out).write_text(json.dumps(gap, ensure_ascii=False, indent=2), encoding="utf-8")
        console.print(f"저장: [green]{out}[/]")
        return
    s = gap["summary"]
    console.print(
        f"의무 {s['obligations']}건 중 [red]{s['uncovered']}건[/]에 통제가 없다"
        f" · 부분 커버 {s['partially_covered']}건"
        f" · 수기 의존 통제 [yellow]{s['manual_controls']}건[/]"
    )
    if gap["uncovered_obligations"]:
        t = Table(show_header=True, title="통제 없는 의무")
        t.add_column("강제력"); t.add_column("의무"); t.add_column("조문")
        for row in gap["uncovered_obligations"]:
            t.add_row(row["level"], row["title"][:60], ", ".join(row["provisions"]))
        console.print(t)
    if gap["manual_controls"]:
        t = Table(show_header=True, title="수기 의존 통제 (자동화 후보)")
        t.add_column("통제"); t.add_column("제목")
        for row in gap["manual_controls"]:
            t.add_row(row["control"], row["title"])
        console.print(t)


@app.command()
def impact(provision: str = typer.Argument(..., help="조문 uuid"), config: str = ConfigOpt):
    """규제 변경 영향분석 — 이 조문이 흔들리면 무엇이 흔들리는가."""
    store, _ = _store(config)
    result = analysis.provision_impact(store.approved(), provision)
    p = result["provision"]
    console.print(f"[bold]{p['number']} {p['title']}[/] ({p['status']})")
    console.print(f"  의무 {len(result['obligations'])}건 → 통제 {len(result['controls'])}건 "
                  f"→ 서비스 {len(result['services'])}건 / 판정 {result['assessments']}건 "
                  f"(확정 {result['confirmed_assessments']}건)")
    if result["controls"]:
        console.print("  통제: " + ", ".join(result["controls"]))
    if result["services"]:
        console.print("  서비스: " + ", ".join(result["services"]))
    for line in result["lineage"]:
        console.print(f"  계보: {line}")


@app.command()
def goldset(config: str = ConfigOpt, today: str = typer.Option(None, "--today")):
    """골드셋 회귀 — 커버리지와 정밀도를 나눠서 잰다."""
    store, cfg = _store(config)
    cases = store.goldset
    if not cases:
        console.print("[yellow]골드셋이 없다.[/] compliance/goldset.json 을 만들어라.")
        raise typer.Exit(code=1)
    report = verify.run_goldset(
        store.approved(), cases, metrics=store.metrics,
        ruleset_version=cfg.ruleset_version, today=today,
    )
    console.print(
        f"골드셋 {report.total}건 — 자동 판정 {report.decided} / 유보 {report.deferred}\n"
        f"  커버리지 [bold]{report.coverage:.0%}[/] · "
        f"정밀도 [bold]{report.precision:.0%}[/] · Cohen κ [bold]{report.kappa:.3f}[/]"
    )
    for miss in report.misses:
        console.print(
            f"  [red]오답[/] {miss['service']}/{miss['control']}: "
            f"기대 {miss['expected']} ≠ 판정 {miss['actual']} — {miss['reason']}"
        )
    console.print("결과: " + ("[green]PASS[/]" if report.passed else "[red]FAIL[/]"))
    if not report.passed:
        raise typer.Exit(code=1)


# --------------------------------------------------------------------------- #
# 커밋 결재
# --------------------------------------------------------------------------- #
changes = typer.Typer(help="커밋 결재 — 지식·기준 변경 승인", no_args_is_help=True)
app.add_typer(changes, name="changes")


@changes.command("list")
def changes_list(config: str = ConfigOpt,
                 all_: bool = typer.Option(False, "--all", "-a", help="종료된 것도 본다")):
    """변경 제안 목록."""
    store, _ = _store(config)
    rows = list(store.read_changesets().values())
    if not all_:
        rows = [r for r in rows if r.get("status") in (cs.PENDING, cs.BLOCKED)]
    t = Table(show_header=True)
    for col in ("ID", "등급", "상태", "제안자", "ops", "영향(통제/판정/서비스)", "파괴"):
        t.add_column(col)
    for raw in sorted(rows, key=lambda r: r.get("changeset_id", "")):
        imp = raw.get("impact", {})
        status = raw.get("status", "")
        color = {"pending_review": "yellow", "approved": "green",
                 "rejected": "dim", "blocked": "red"}.get(status, "white")
        t.add_row(
            raw.get("changeset_id", ""), raw.get("grade", ""), f"[{color}]{status}[/]",
            (raw.get("proposer") or {}).get("id", ""), str(len(raw.get("ops", []))),
            f"{imp.get('affected_controls', 0)} / {imp.get('affected_assessments', 0)}"
            f" / {imp.get('affected_services', 0)}",
            "[red]★[/]" if imp.get("breaking") else "",
        )
    console.print(t)


@changes.command("show")
def changes_show(changeset_id: str = typer.Argument(...), config: str = ConfigOpt):
    """제안 하나의 diff 와 검증 결과."""
    store, _ = _store(config)
    raw = store.changeset(changeset_id)
    if raw is None:
        console.print(f"[red]없는 제안:[/] {changeset_id}")
        raise typer.Exit(code=1)
    change = cs.ChangeSet.from_dict(raw)
    console.print(cs.summary_line(change))
    console.print(f"  결재선: {cs.GRADES[change.grade]['approver']} — "
                  f"{cs.GRADES[change.grade]['scope']}")
    console.print(f"  기계 검증: {change.checks.get('shacl')}")
    for issue in change.checks.get("issues", []):
        console.print(f"    [red]{issue['code']}[/] {issue['message']}")
    if change.status in (cs.PENDING, cs.BLOCKED):
        d = cs.diff(store, change)
        console.print(f"  추가 노드 {len(d['added_nodes'])} / 추가 엣지 {len(d['added_edges'])} "
                      f"/ 속성 변경 {len(d['changed_nodes'])} / 폐기 {len(d['obsoleted'])}")
        for node in d["added_nodes"][:10]:
            console.print(f"    + {node['type']} {node['id']}")
        for node in d["changed_nodes"][:10]:
            console.print(f"    ~ {node['id']}: {node['changes']}")


@changes.command("approve")
def changes_approve(
    changeset_id: str = typer.Argument(...),
    by: str = typer.Option(..., "--by", help="결재자"),
    note: str = typer.Option("", "--note"),
    config: str = ConfigOpt,
):
    """게이트 2 — 병합한다. 여기서부터 판정 엔진이 본다."""
    store, _ = _store(config)
    change = cs.approve(store, changeset_id, approver=by, note=note)
    console.print(f"[green]병합[/] {cs.summary_line(change)} (by {by})")


@changes.command("reject")
def changes_reject(
    changeset_id: str = typer.Argument(...),
    by: str = typer.Option(..., "--by"),
    note: str = typer.Option("", "--note"),
    config: str = ConfigOpt,
):
    """반려한다. 이력은 남는다."""
    store, _ = _store(config)
    cs.reject(store, changeset_id, reviewer=by, note=note)
    console.print(f"[yellow]반려[/] {changeset_id} (by {by})")


# --------------------------------------------------------------------------- #
# 제안 (L1)
# --------------------------------------------------------------------------- #
@app.command("ingest")
def ingest(
    path: str = typer.Argument(..., help="규제 원문 텍스트 파일"),
    uuid: str = typer.Option(..., "--uuid", help="Regulation 앵커 UUID"),
    name: str = typer.Option(..., "--name"),
    issuer: str = typer.Option("", "--issuer"),
    doc_id: str = typer.Option(None, "--doc-id"),
    effective_from: str = typer.Option("", "--effective-from"),
    config: str = ConfigOpt,
):
    """L0 — 규제 문서(docx·xlsx·pdf·txt)를 조문 단위로 쪼개 불변 앵커와 함께 제안한다."""
    store, _ = _store(config)
    result = propose.ingest_regulation(
        store, path=path, doc_id=doc_id or "", regulation_uuid=uuid, name=name,
        issuer=issuer or "미상", effective_from=effective_from,
    )
    change = cs.stage(store, result.ops,
                      proposer={"type": "SoftwareAgent", "id": "collector-v1"},
                      source={"type": "document", "id": Path(path).name})
    console.print(result.note)
    if result.parsed is not None and result.parsed.warnings:
        for w in result.parsed.warnings:
            console.print(f"  [yellow]경고[/] {w}")
    console.print(cs.summary_line(change))


@app.command("template")
def template_cmd(
    control: str = typer.Argument(..., help="통제 코드"),
    path: str = typer.Argument(..., help="회사 서식 파일 (별첨 등)"),
    seq: str = typer.Option("S1", "--seq"),
    max_level: int = typer.Option(2, "--max-level", help="이 깊이까지만 필수 절로 본다"),
    config: str = ConfigOpt,
):
    """서식에서 필수 절을 뽑아 구성 검토 절차를 제안한다 (체크리스트를 손으로 안 만든다)."""
    store, _ = _store(config)
    result = propose.propose_section_procedure(
        control, path, seq=seq, max_level=max_level)
    sections = result.ops[0]["props"]["sections"]
    for label in sections:
        console.print(f"  · {label}")
    change = cs.stage(store, result.ops, proposer={"type": "Person", "id": "gov"},
                      source={"type": "template", "id": Path(path).name})
    console.print(f"{result.note}\n{cs.summary_line(change)}")


@app.command("submit")
def submit(
    path: str = typer.Argument(..., help="직원 작업물 (docx·xlsx·pdf)"),
    uuid: str = typer.Option(..., "--uuid", help="Evidence 앵커"),
    title: str = typer.Option("", "--title"),
    kind: str = typer.Option("", "--kind", help="증적 종류"),
    control: str = typer.Option("", "--control", help="이 통제의 증적으로 제출"),
    service: str = typer.Option("", "--service"),
    signed: bool = typer.Option(False, "--signed", help="서명 완료본"),
    signer: str = typer.Option("", "--signer"),
    valid_from: str = typer.Option("", "--valid-from"),
    valid_to: str = typer.Option("", "--valid-to"),
    config: str = ConfigOpt,
):
    """작업물을 증적으로 적재 제안한다. 절 목록과 미기입 자리를 함께 기록한다."""
    store, _ = _store(config)
    result = propose.ingest_work_product(
        store, path, evidence_uuid=uuid, title=title, evidence_kind=kind,
        sign_yn=signed, signer=signer, valid_from=valid_from, valid_to=valid_to,
        control_code=control, service_uuid=service,
    )
    console.print(result.note)
    holes = result.ops[0]["props"].get("placeholders") or []
    for h in holes[:8]:
        console.print(f"  [yellow]미기입 의심[/] {h['why']} — {h['quote'][:60]}")
    change = cs.stage(store, result.ops, proposer={"type": "Person", "id": "submitter"},
                      source={"type": "work-product", "id": Path(path).name})
    console.print(cs.summary_line(change))


@app.command("consistency")
def consistency_cmd(
    config: str = ConfigOpt,
    out: str = typer.Option(None, "--out", "-o"),
):
    """문서 간 정합성 — 같은 값을 말하는 문서끼리 값이 다른 곳을 찾는다."""
    from . import consistency as cons
    from .docparse import ParsedDoc, detect_sections

    store, _ = _store(config)
    docs = []
    for doc_id, text in store.documents().items():
        d = ParsedDoc(doc_id, doc_id, "txt", text)
        d.sections = detect_sections(text)
        docs.append(d)
    conflicts = cons.compare(docs)
    if out:
        Path(out).write_text(
            json.dumps(cons.report(conflicts), ensure_ascii=False, indent=2),
            encoding="utf-8")
        console.print(f"저장: [green]{out}[/]")
        return
    if not conflicts:
        console.print(f"문서 {len(docs)}건 대조 — [green]불일치 없음[/]")
        return
    console.print(f"문서 {len(docs)}건 대조 — [red]불일치 {len(conflicts)}건[/]")
    t = Table(show_header=True)
    t.add_column("값 이름"); t.add_column("서로 다른 값"); t.add_column("문서")
    for c in conflicts:
        t.add_row(c.key, " ≠ ".join(sorted(c.values)), ", ".join(c.documents))
    console.print(t)


@app.command("link")
def link(
    path: str = typer.Argument(..., help="작업물"),
    service: str = typer.Option(..., "--service"),
    evidence: str = typer.Option("", "--evidence", help="이미 적재한 Evidence 앵커"),
    config: str = ConfigOpt,
):
    """사내 sLM 이 이 문서가 어느 통제의 증적인지 제안한다 (판정하지 않는다)."""
    from ..llm import get_provider
    from .docparse import parse as parse_doc

    store, cfg = _store(config)
    provider = get_provider(cfg.provider, cfg.llm_options)
    console.print(f"sLM: [bold]{cfg.provider}[/] ({cfg.llm_options.get('model')})")
    parsed = parse_doc(path)
    result = propose.propose_evidence_links(
        store, parsed, store.approved(), service_uuid=service,
        provider=provider, evidence_uuid=evidence,
    )
    console.print(result.note)
    for row in result.rejected:
        console.print(f"  [red]탈락[/] {row['reason']}")
    if not result.ops:
        raise typer.Exit(code=0)
    for op in result.ops:
        console.print(f"  제안: {op['source']} → {op['target']}")
    change = cs.stage(store, result.ops, proposer=propose.SLM_AGENT,
                      source={"type": "evidence-link", "id": Path(path).name})
    console.print(cs.summary_line(change))


@app.command("propose")
def propose_cmd(
    config: str = ConfigOpt,
    provision: str = typer.Option(None, "--provision", help="특정 조문 uuid 만"),
    use_llm: bool = typer.Option(False, "--llm", help="sLM 을 부른다 (기본은 기준선 추출기)"),
):
    """L1 — 조문에서 의무를 뽑아 **제안**한다. 승인 그래프에 직접 쓰지 않는다."""
    store, cfg = _store(config)
    g = store.approved()
    provisions = [
        n for n in g.of_type("Provision")
        if not provision or n["props"].get("uuid") == provision
    ]
    if not provisions:
        console.print("[yellow]조문이 없다.[/] 먼저 `llmwiki reg ingest` 를 돌려라.")
        raise typer.Exit(code=1)
    provider = None
    if use_llm:
        from ..llm import get_provider
        provider = get_provider(cfg.provider, cfg.llm_options)
        console.print(f"sLM: [bold]{cfg.provider}[/] ({cfg.llm_options.get('model')})")
    result = propose.propose_obligations(store, provisions, provider=provider)
    change = cs.stage(store, result.ops, proposer=propose.SLM_AGENT,
                      source={"type": "provision-extract", "id": "batch"})
    console.print(result.note)
    for row in result.rejected:
        console.print(f"  [red]탈락[/] {row['reason']}")
    console.print(cs.summary_line(change))


@app.command("link-programs")
def link_programs(config: str = ConfigOpt):
    """LLMWiki 가 뽑은 운영 프로그램을 증적 생산 기능으로 제안한다."""
    from ..indexer import load_index

    store, cfg = _store(config)
    idx = load_index(cfg, with_source=False)
    result = propose.propose_system_functions(idx, system=cfg.project_name)
    if not result.ops:
        console.print("[yellow]프로그램이 없다.[/] 먼저 `llmwiki parse` 를 돌려라.")
        raise typer.Exit(code=1)
    change = cs.stage(store, result.ops,
                      proposer={"type": "SoftwareAgent", "id": "llmwiki-bridge"},
                      source={"type": "llmwiki", "id": cfg.project_name})
    console.print(f"{result.note}\n{cs.summary_line(change)}")


def _prior_verdicts(g: Any) -> dict[str, dict[str, str]]:
    """직전 차수 판정 — 결과가 뒤집히면 유보한다."""
    prior: dict[str, dict[str, str]] = {}
    for node in sorted(g.of_type("Assessment"),
                       key=lambda n: str(n["props"].get("assessed_at", ""))):
        props = node["props"]
        svc, code = props.get("service_uuid"), props.get("control_code")
        if svc and code:
            prior.setdefault(str(svc), {})[str(code)] = str(props.get("verdict"))
    return prior


__all__ = ["app", "RULESET_VERSION"]
