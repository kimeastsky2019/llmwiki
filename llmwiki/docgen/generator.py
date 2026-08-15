"""프로그램별 MD 산출물 생성.

정확해야 하는 사실(테이블, CRUD, SQL 원문, 영향도, 원본 경로)은 파서가 만든다.
LLM 은 설명·서술 부분만 담당한다. 이렇게 나눠야 산출물이 거짓말을 하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from ..i18n import label
from ..llm import get_provider
from ..models import Program
from ..parsers.graph import Index, impact_of
from .prompts import build_prompt, system_prompt


def generate_all(
    cfg: Config,
    idx: Index,
    *,
    only: str | None = None,
    force: bool = False,
    on_progress: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    provider = get_provider(cfg.provider, cfg.llm_options)
    cfg.docs_dir.mkdir(parents=True, exist_ok=True)

    targets = [p for p in idx.programs if only is None or p.id == only]
    if only and not targets:
        raise ValueError(f"프로그램을 찾을 수 없습니다: {only}")

    results = {"generated": [], "skipped": [], "failed": []}

    def work(prog: Program) -> tuple[str, str, str]:
        digest = _source_hash(cfg, idx, prog)
        out_path = cfg.docs_dir / f"{prog.id}.md"
        if not force and out_path.exists() and _existing_hash(out_path) == digest:
            return prog.id, "skipped", ""
        body = _render(cfg, idx, prog, provider, digest)
        out_path.write_text(body, encoding="utf-8")
        return prog.id, "generated", ""

    with ThreadPoolExecutor(max_workers=max(1, cfg.concurrency)) as pool:
        futures = {pool.submit(work, p): p for p in targets}
        for fut in as_completed(futures):
            prog = futures[fut]
            try:
                pid, status, _ = fut.result()
                results[status].append(pid)
                if on_progress:
                    on_progress(pid, status)
            except Exception as exc:  # noqa: BLE001
                results["failed"].append({"id": prog.id, "error": str(exc)})
                if on_progress:
                    on_progress(prog.id, f"failed: {exc}")

    return results


def generate_one(cfg: Config, idx: Index, program_id: str, *, force: bool = True):
    return generate_all(cfg, idx, only=program_id, force=force)


# --------------------------------------------------------------------------- #
def _render(cfg: Config, idx: Index, prog: Program, provider, digest: str) -> str:
    sources = _collect_sources(cfg, idx, prog)
    statements = [
        _statement_dict(idx.statements[sid]) for sid in prog.sql_ids if sid in idx.statements
    ]
    crud_rows = _crud_rows(idx, prog)

    lang = cfg.language
    prompt = build_prompt(
        program_name=prog.name,
        layer=prog.layer,
        entry_fqn=prog.entry_fqn,
        urls=prog.urls,
        tables=prog.tables,
        crud_rows=crud_rows,
        sources=sources,
        statements=statements,
        lang=lang,
    )
    narrative = provider.complete(system_prompt(lang), prompt).strip()
    narrative = _strip_frontmatter(narrative)

    front = _frontmatter(cfg, prog, digest, provider)
    appendix = _appendix(idx, prog, crud_rows, statements, lang)
    return f"{front}\n{narrative}\n\n{appendix}"


def _frontmatter(cfg: Config, prog: Program, digest: str, provider) -> str:
    data = {
        "id": prog.id,
        "name": prog.name,
        "layer": prog.layer,
        "tier": prog.tier,
        "entry": prog.entry_fqn,
        "urls": prog.urls,
        "classes": prog.classes,
        "mappers": prog.mappers,
        "sql_ids": prog.sql_ids,
        "tables": prog.tables,
        "service_ids": prog.service_ids,
        "files": prog.files,
        "language": cfg.language,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "generator": f"{provider.name}:{getattr(provider, 'model', '')}",
        "source_hash": digest,
    }
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  - {_yaml_scalar(v)}" for v in value)
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _yaml_scalar(value: Any) -> str:
    s = str(value)
    if s == "":
        return '""'
    if any(ch in s for ch in ':#{}[]&*!|>\'"%@`') or s.strip() != s:
        return json.dumps(s, ensure_ascii=False)
    return s


def _appendix(idx: Index, prog: Program, crud_rows, statements, lang: str = "ko") -> str:
    def L(key: str) -> str:
        return label(key, lang)

    out: list[str] = ["", "---", "", f"> {L('appendix_note')}", ""]

    out.append(f"## {L('appendix_a')}")
    out.append("")
    out.append(_mermaid_flow(idx, prog, lang))
    out.append("")

    out.append(f"## {L('appendix_b')}")
    if crud_rows:
        by_table: dict[str, set[str]] = {}
        for table, op in crud_rows:
            by_table.setdefault(table, set()).add(op)
        out.append(L("crud_header"))
        out.append("|---|:-:|:-:|:-:|:-:|")
        for table in sorted(by_table):
            ops = by_table[table]
            out.append(
                f"| {table} | "
                + " | ".join("●" if op in ops else "" for op in ("C", "R", "U", "D"))
                + " |"
            )
    else:
        out.append(L("no_tables"))
    out.append("")

    out.append(f"## {L('appendix_c')}")
    impact = impact_of(idx, prog.id)
    if impact["affected"]:
        out.append(L("impact_intro"))
        out.append("")
        out.append(L("impact_header"))
        out.append("|---|---|---|")
        for row in impact["affected"][:30]:
            out.append(f"| [{row['name']}](/p/{row['id']}) | {row['layer']} | {', '.join(row['tables'])} |")
    else:
        out.append(L("no_impact"))
    out.append("")

    out.append(f"## {L('appendix_d')}")
    if statements:
        for st in statements:
            out.append(f"### `{st['full_id']}` — {st['kind']}")
            out.append(f"- {L('sql_file')}: `{st['path']}` (line {st['line']})")
            out.append(f"- {L('sql_params')}: {', '.join(st['params']) or L('none')}")
            out.append("")
            out.append("```sql")
            out.append(st["sql"])
            out.append("```")
            out.append("")
    else:
        out.append(L("no_sql"))
        out.append("")

    out.append(f"## {L('appendix_e')}")
    for f in prog.files:
        out.append(f"- `{f}`")
    out.append("")
    return "\n".join(out)


KIND_SHAPE = {
    "controller": ("[", "]"),
    "service": ("([", "])"),
    "serviceimpl": ("[", "]"),
    "mapper": ("[/", "/]"),
    "dao": ("[/", "/]"),
    "sql": ("[(", ")]"),
    "table": ("[(", ")]"),
}


def _mermaid_flow(idx: Index, prog: Program, lang: str = "ko") -> str:
    """정적 분석된 호출 그래프를 그대로 mermaid 로 렌더한다(추측 없음)."""
    members = set(prog.classes)
    node_ids: dict[str, str] = {}
    lines: list[str] = ["```mermaid", "flowchart LR"]
    edges: list[str] = []

    def nid(key: str) -> str:
        if key not in node_ids:
            node_ids[key] = f"n{len(node_ids)}"
        return node_ids[key]

    declared: set[str] = set()

    def declare(key: str, label: str, kind: str) -> str:
        ident = nid(key)
        if ident not in declared:
            declared.add(ident)
            open_b, close_b = KIND_SHAPE.get(kind, ("[", "]"))
            lines.append(f'    {ident}{open_b}"{_esc(label)}"{close_b}')
        return ident

    for src, dst, kind in idx.edges:
        src_cls = src.split("#")[0]
        if src_cls not in members or src_cls not in idx.classes:
            continue
        if idx.classes[src_cls].kind in ("vo", "util"):
            continue

        if kind == "sql":
            # SQL 문은 별도 노드로 그리지 않고, 매퍼 메서드에서 테이블로 바로 잇는다
            if dst not in prog.sql_ids:
                continue
            st = idx.statements.get(dst)
            if not st:
                continue
            a = declare(src, _short(src), idx.classes[src_cls].kind)
            for table, op in st.crud:
                b = declare(f"table:{table}", table, "table")
                edges.append(f"    {a} -->|{op}| {b}")
            continue

        dst_cls = dst.split("#")[0]
        if dst_cls not in members or dst_cls not in idx.classes:
            continue
        if idx.classes[dst_cls].kind in ("vo", "util"):
            continue
        a = declare(src, _short(src), idx.classes[src_cls].kind)
        b = declare(dst, _short(dst), idx.classes[dst_cls].kind)
        arrow = "-.->" if kind == "impl" else "-->"
        edges.append(f"    {a} {arrow} {b}")

    if not edges:
        return label("no_calls", lang)

    lines.extend(sorted(set(edges)))
    lines.append("```")
    return "\n".join(lines)


def _short(node: str) -> str:
    cls, _, method = node.partition("#")
    return f"{cls.split('.')[-1]}.{method}" if method else cls.split(".")[-1]


def _esc(text: str) -> str:
    return text.replace('"', "'")


def _collect_sources(cfg: Config, idx: Index, prog: Program) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    limit = cfg.max_class_chars
    for fqn in prog.classes:
        cls = idx.classes.get(fqn)
        if not cls or cls.kind in ("vo", "util"):
            continue
        code = cls.source or ""
        if len(code) > limit:
            code = _signatures_only(cls)
        out.append((cls.path, code))
    # VO 는 시그니처만 (I/O 파라미터 문서화에 필요)
    for fqn in prog.classes:
        cls = idx.classes.get(fqn)
        if cls and cls.kind == "vo":
            out.append((cls.path, _signatures_only(cls)))
    return out


def _signatures_only(cls) -> str:
    lines = [f"// (본문 생략 — 시그니처만) {cls.fqn}"]
    for ftype, fname in cls.fields:
        lines.append(f"  {ftype} {fname};")
    for m in cls.methods:
        params = ", ".join(f"{t} {n}" for t, n in m.params)
        ann = " ".join(m.annotations)
        lines.append(f"  {ann} {m.return_type} {m.name}({params});".strip())
    return "\n".join(lines)


def _statement_dict(st) -> dict[str, Any]:
    return {
        "full_id": st.full_id,
        "kind": st.kind,
        "sql": st.sql,
        "params": st.params,
        "parameter_type": st.parameter_type,
        "result_type": st.result_type,
        "path": st.path,
        "line": st.line,
    }


def _crud_rows(idx: Index, prog: Program) -> list[tuple[str, str]]:
    rows: set[tuple[str, str]] = set()
    for sid in prog.sql_ids:
        st = idx.statements.get(sid)
        if not st:
            continue
        for table, op in st.crud:
            rows.add((table, op))
    return sorted(rows)


def _source_hash(cfg: Config, idx: Index, prog: Program) -> str:
    h = hashlib.sha256()
    h.update(prog.entry_fqn.encode())
    for fqn in prog.classes:
        cls = idx.classes.get(fqn)
        if cls:
            h.update(cls.source.encode())
    for sid in prog.sql_ids:
        st = idx.statements.get(sid)
        if st:
            h.update(st.sql.encode())
    return h.hexdigest()[:16]


def _existing_hash(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8") as f:
            if f.readline().strip() != "---":
                return None
            for line in f:
                if line.strip() == "---":
                    return None
                if line.startswith("source_hash:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    return parts[2].strip() if len(parts) >= 3 else text
