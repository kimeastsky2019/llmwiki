"""Java 소스 정적 분석 (Spring + MyBatis 관례 기반).

완전한 컴파일러가 아니라 '산출물 생성에 필요한 구조'만 뽑는다.
주석/문자열은 scanner 로 먼저 제거하므로 중괄호 매칭이 깨지지 않는다.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..models import JavaClass, JavaMethod
from .scanner import Scrubbed, find_block, line_of, scrub

PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)
IMPORT_RE = re.compile(r"^\s*import\s+(?:static\s+)?([\w.*]+)\s*;", re.M)
TYPE_DECL_RE = re.compile(
    r"\b(?P<kw>class|interface|enum)\s+(?P<name>\w+)"
    r"(?P<generics><[^{]*?>)?"
    r"(?:\s+extends\s+(?P<extends>[\w.<>,\s]+?))?"
    r"(?:\s+implements\s+(?P<implements>[\w.<>,\s]+?))?"
    r"\s*\{"
)
ANNOTATION_RE = re.compile(r"@(\w+)\s*(\([^)]*\))?")
CALL_RE = re.compile(r"(\w+)\s*\.\s*(\w+)\s*\(")
NESTED_TYPE_RE = re.compile(r"\b(?:class|interface|enum)\s+\w")
LOCAL_VAR_RE = re.compile(r"\b([A-Z][\w.]*(?:<[^;=]*>)?)\s+(\w+)\s*=")

# MyBatis SqlSession 직접 호출 (레거시 DAO 관례)
SQLSESSION_CALL_RE = re.compile(
    r"\.\s*(selectList|selectOne|insert|update|delete|queryForList|queryForObject"
    r"|selectMap|selectCursor)\s*\(\s*(\x00S\d+\x00)"
)

MAPPING_ANNOTATIONS = {
    "RequestMapping",
    "GetMapping",
    "PostMapping",
    "PutMapping",
    "DeleteMapping",
    "PatchMapping",
}

_PRIMITIVES = {
    "void", "int", "long", "short", "byte", "char", "boolean", "float", "double",
    "return", "if", "for", "while", "switch", "new", "throw", "else", "try", "catch",
    "synchronized", "do", "finally", "assert",
}


def parse_java_file(path: Path, root: Path) -> list[JavaClass]:
    try:
        src = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        src = path.read_text(encoding="euc-kr", errors="replace")

    sc = scrub(src)
    text = sc.text

    pkg_m = PACKAGE_RE.search(text)
    package = pkg_m.group(1) if pkg_m else ""
    imports = IMPORT_RE.findall(text)

    rel = str(path.relative_to(root)) if _is_relative(path, root) else str(path)

    classes: list[JavaClass] = []
    for m in TYPE_DECL_RE.finditer(text):
        if m.group("kw") == "enum":
            continue
        open_idx = text.index("{", m.end() - 1)
        close_idx = find_block(text, open_idx)
        if close_idx == -1:
            continue

        # 중첩 클래스는 최상위 클래스에 흡수 (별도 문서로 만들지 않는다)
        if any(
            c._span[0] < m.start() < c._span[1]  # type: ignore[attr-defined]
            for c in classes
        ):
            continue

        annotations = _annotations_before(text, m.start(), sc)
        body = text[open_idx + 1 : close_idx]

        cls = JavaClass(
            path=rel,
            package=package,
            name=m.group("name"),
            is_interface=m.group("kw") == "interface",
            annotations=annotations,
            extends=(m.group("extends") or "").strip() or None,
            implements=[
                s.strip() for s in (m.group("implements") or "").split(",") if s.strip()
            ],
            imports=imports,
            source=src,
        )
        cls._span = (m.start(), close_idx)  # type: ignore[attr-defined]

        fields, methods = _parse_members(body, open_idx + 1, text, sc, cls.name)
        cls.fields = fields
        cls.methods = methods
        cls.class_mapping = _first_mapping(annotations, sc)
        cls.kind = _classify(cls)
        classes.append(cls)

    for c in classes:
        if hasattr(c, "_span"):
            delattr(c, "_span")
    return classes


def _is_relative(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _annotations_before(text: str, decl_start: int, sc: Scrubbed) -> list[str]:
    """선언 앞쪽에서 어노테이션 블록을 역방향으로 수집."""
    head = text[max(0, decl_start - 2000) : decl_start]
    # 마지막 ';' 또는 '}' 이후만 본다
    cut = max(head.rfind(";"), head.rfind("}"), head.rfind("{"))
    head = head[cut + 1 :]
    return [sc.restore(m.group(0)) for m in ANNOTATION_RE.finditer(head)]


def _parse_members(
    body: str, body_offset: int, full_text: str, sc: Scrubbed, class_name: str
) -> tuple[list[list[str]], list[JavaMethod]]:
    fields: list[list[str]] = []
    methods: list[JavaMethod] = []

    i = 0
    seg_start = 0
    depth = 0
    paren = 0
    n = len(body)

    while i < n:
        ch = body[i]
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren -= 1
        elif ch == "{" and paren == 0:
            sig = body[seg_start:i]
            # `Exception.class` 의 class 를 중첩 타입 선언으로 오인하면 안 된다.
            # 선언은 반드시 `class 이름` 처럼 식별자가 뒤따른다.
            if NESTED_TYPE_RE.search(ANNOTATION_RE.sub("", sig)):
                # 중첩 타입 — 통째로 건너뛴다
                end = find_block(body, i)
                i = (end if end != -1 else n) + 1
                seg_start = i
                continue
            end = find_block(body, i)
            if end == -1:
                break
            method = _make_method(
                sig, body[i + 1 : end], sc, class_name,
                line_of(full_text, body_offset + seg_start),
                line_of(full_text, body_offset + end),
            )
            if method:
                methods.append(method)
            i = end + 1
            seg_start = i
            continue
        elif ch == ";" and paren == 0:
            seg = body[seg_start:i]
            # @Resource(name = "x") 같은 어노테이션의 괄호를 메서드 괄호로 오인하면 안 된다
            bare = ANNOTATION_RE.sub("", seg)
            if "(" in bare and ")" in bare and not re.search(r"\b(class|interface)\b", bare):
                # 인터페이스 추상 메서드
                method = _make_method(
                    seg, "", sc, class_name,
                    line_of(full_text, body_offset + seg_start),
                    line_of(full_text, body_offset + i),
                )
                if method:
                    methods.append(method)
            else:
                fld = _make_field(seg)
                if fld:
                    fields.append(fld)
            i += 1
            seg_start = i
            continue
        i += 1

    return fields, methods


def _make_field(seg: str) -> list[str] | None:
    clean = ANNOTATION_RE.sub("", seg).strip()
    clean = re.sub(
        r"\b(private|protected|public|static|final|transient|volatile)\b", "", clean
    ).strip()
    if not clean:
        return None
    clean = clean.split("=")[0].strip()
    m = re.match(r"^([\w.]+(?:\s*<[^;]*>)?(?:\s*\[\s*\])*)\s+(\w+)$", clean)
    if not m:
        return None
    return [re.sub(r"\s+", "", m.group(1)), m.group(2)]


def _make_method(
    sig: str, body: str, sc: Scrubbed, class_name: str, line_start: int, line_end: int
) -> JavaMethod | None:
    annotations = [sc.restore(m.group(0)) for m in ANNOTATION_RE.finditer(sig)]
    clean = ANNOTATION_RE.sub("", sig).strip()
    clean = re.sub(r"\bthrows\s+[\w.,\s<>]+$", "", clean).strip()
    m = re.search(
        r"(?:^|\s)(?P<ret>[\w.<>,\[\]?\s]+?\s+)?(?P<name>\w+)\s*\((?P<params>[^)]*)\)\s*$",
        clean,
        re.S,
    )
    if not m:
        return None
    name = m.group("name")
    if name in _PRIMITIVES or name == class_name:
        return None  # 생성자/제어문
    ret = re.sub(r"\b(public|private|protected|static|final|abstract|synchronized|default)\b", "", m.group("ret") or "")
    ret = re.sub(r"\s+", " ", ret).strip()
    if not ret:
        return None

    params = _split_params(m.group("params"))
    calls = _extract_calls(body)
    sql_refs = [sc.restore(g[1]).strip("\"'") for g in SQLSESSION_CALL_RE.findall(body)]

    return JavaMethod(
        name=name,
        return_type=ret,
        params=params,
        annotations=annotations,
        url_mappings=_mappings(annotations),
        line_start=line_start,
        line_end=line_end,
        calls=calls,
        sql_refs=sql_refs,
        body=sc.restore(body).strip(),
    )


def _split_params(raw: str) -> list[list[str]]:
    out: list[list[str]] = []
    depth = 0
    buf: list[str] = []
    parts: list[str] = []
    for ch in raw:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if "".join(buf).strip():
        parts.append("".join(buf))

    for p in parts:
        p = ANNOTATION_RE.sub("", p).strip()
        p = re.sub(r"\bfinal\b", "", p).strip()
        toks = p.rsplit(" ", 1)
        if len(toks) == 2:
            out.append([re.sub(r"\s+", "", toks[0]), toks[1]])
        elif p:
            out.append([p, ""])
    return out


def _extract_calls(body: str) -> list[list[str]]:
    seen: set[tuple[str, str]] = set()
    out: list[list[str]] = []
    for recv, meth in CALL_RE.findall(body):
        if recv in _PRIMITIVES or meth in _PRIMITIVES:
            continue
        key = (recv, meth)
        if key in seen:
            continue
        seen.add(key)
        out.append([recv, meth])
    return out


def _mappings(annotations: list[str]) -> list[str]:
    urls: list[str] = []
    for a in annotations:
        m = ANNOTATION_RE.match(a)
        if not m or m.group(1) not in MAPPING_ANNOTATIONS:
            continue
        args = m.group(2) or ""
        urls.extend(re.findall(r'"([^"]+)"', args))
    return urls


def _first_mapping(annotations: list[str], sc: Scrubbed) -> str:
    urls = _mappings(annotations)
    return urls[0] if urls else ""


def _classify(cls: JavaClass) -> str:
    ann = " ".join(cls.annotations)
    name = cls.name
    if "@RestController" in ann or "@Controller" in ann or name.endswith("Controller"):
        return "controller"
    if "@Mapper" in ann or name.endswith("Mapper"):
        return "mapper"
    if "@Repository" in ann or name.endswith(("DAO", "Dao")):
        return "dao"
    if name.endswith("ServiceImpl"):
        return "serviceimpl"
    if "@Service" in ann or name.endswith("Service"):
        return "service"
    if name.endswith(("VO", "Vo", "DTO", "Dto", "Entity")):
        return "vo"
    if name.endswith(("Util", "Utils", "Helper", "Constants")):
        return "util"
    return "unknown"
