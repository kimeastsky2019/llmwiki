"""MyBatis Mapper XML 파서.

동적 태그(<if>, <foreach>, <where> …)는 텍스트를 그대로 이어붙여
'가능한 최대 SQL' 형태로 만든 뒤 테이블/파라미터를 추출한다.
<include refid="..."/> 는 <sql> 조각으로 치환한다.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models import MapperXml, SqlStatement

DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>]*>", re.S)
STATEMENT_TAGS = {"select", "insert", "update", "delete"}

TABLE_PATTERNS = [
    (re.compile(r"\bfrom\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.I), "R"),
    (re.compile(r"\bjoin\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.I), "R"),
    (re.compile(r"\binsert\s+into\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.I), "C"),
    (re.compile(r"\bupdate\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.I), "U"),
    (re.compile(r"\bdelete\s+from\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.I), "D"),
    (re.compile(r"\bmerge\s+into\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)?)", re.I), "U"),
]

PARAM_RE = re.compile(r"[#$]\{\s*([\w.]+)")
NOISE_TABLES = {"dual", "select", "where", "set", "values", "table"}


def parse_mapper_xml(path: Path, root: Path) -> MapperXml | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="euc-kr", errors="replace")

    if "<mapper" not in raw:
        return None

    cleaned = DOCTYPE_RE.sub("", raw)
    try:
        tree = ET.fromstring(cleaned)
    except ET.ParseError:
        return None
    if tree.tag != "mapper":
        return None

    namespace = tree.get("namespace", "")
    rel = str(path.relative_to(root)) if _is_relative(path, root) else str(path)

    fragments = {
        el.get("id", ""): _flatten(el, {}) for el in tree.findall("sql") if el.get("id")
    }

    line_index = _line_index(raw)
    statements: list[SqlStatement] = []
    for el in tree:
        if el.tag not in STATEMENT_TAGS:
            continue
        sid = el.get("id")
        if not sid:
            continue
        sql = _normalize(_flatten(el, fragments))
        tables, crud = _tables(sql, el.tag)
        statements.append(
            SqlStatement(
                id=sid,
                namespace=namespace,
                kind=el.tag,
                sql=sql,
                tables=tables,
                crud=crud,
                params=sorted({p.split(".")[0] for p in PARAM_RE.findall(sql)}),
                parameter_type=el.get("parameterType"),
                result_type=el.get("resultType") or el.get("resultMap"),
                path=rel,
                line=line_index.get(sid, 0),
            )
        )

    return MapperXml(path=rel, namespace=namespace, statements=statements)


def _is_relative(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _flatten(el: ET.Element, fragments: dict[str, str]) -> str:
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        if child.tag == "include":
            refid = child.get("refid", "")
            parts.append(fragments.get(refid, f" /* include:{refid} */ "))
        else:
            parts.append(_flatten(child, fragments))
        if child.tail:
            parts.append(child.tail)
    return " ".join(parts)


def _normalize(sql: str) -> str:
    lines = [ln.rstrip() for ln in sql.strip().splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    if not lines:
        return ""
    indents = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
    base = min(indents) if indents else 0
    return "\n".join(ln[base:] if len(ln) >= base else ln for ln in lines)


def _tables(sql: str, kind: str) -> tuple[list[str], list[list[str]]]:
    found: dict[str, set[str]] = {}
    flat = re.sub(r"\s+", " ", sql)
    for pattern, op in TABLE_PATTERNS:
        for name in pattern.findall(flat):
            key = name.upper()
            if key.lower() in NOISE_TABLES or key.startswith("("):
                continue
            found.setdefault(key, set()).add(op)

    tables = sorted(found)
    crud = sorted(
        [[t, op] for t, ops in found.items() for op in sorted(ops)],
        key=lambda x: (x[0], x[1]),
    )
    return tables, crud


def _line_index(raw: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in re.finditer(r'<(?:select|insert|update|delete)\b[^>]*id\s*=\s*"([^"]+)"', raw):
        out.setdefault(m.group(1), raw.count("\n", 0, m.start()) + 1)
    return out
