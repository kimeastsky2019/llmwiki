"""수집(L0)과 이해(L1) — sLM 은 **제안만** 한다.

이 파일의 출력은 언제나 `ChangeSet` 이다. 승인 그래프에 직접 쓰는 경로가 없다.
모델이 뽑은 것이 곧바로 기준이 되지 않는다는 것을 코드 구조로 보장한다.

환각을 막는 방식이 프롬프트가 아니라는 점이 핵심이다. 모델에게 "원문 그대로
인용하라" 고 시키되, 받은 인용문을 **원문에서 다시 찾아** 오프셋을 우리가 계산한다.
찾지 못하면 그 제안은 버린다. 그럴듯하게 지어낸 문장은 원문에 없으므로 여기서 죽는다.
모델의 성실성에 기대지 않는 유일한 방법이다.

`propose_system_functions` 는 LLMWiki 본체와 만나는 지점이다. 운영 소스에서 이미
뽑아 둔 Program 을 증적 생산 기능(SystemFunction)으로 잇는다. 이 연결이 있어야
"이 통제의 증적은 수기로 만들어진다" 를 사실로 말할 수 있다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from pathlib import Path

from . import docparse
from .changeset import create_edge, create_node
from .ontology import node_id
from .spans import FORCE_MUST, FORCE_SHOULD, Span, digest, force_of, locate_quote
from .store import Store

SLM_AGENT = {"type": "SoftwareAgent", "id": "slm-extract-v1"}


@dataclass
class Proposal:
    """제안 결과 — 만든 것과 버린 것을 함께 돌려준다.

    버린 것을 감추면 "모델이 잘 뽑았다" 는 착각이 남는다. 근거 대조에서 몇 건이
    떨어졌는지가 그 자체로 품질 지표다.
    """

    ops: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""
    #: 문서에서 온 제안이면 파싱 결과를 함께 돌려준다 (절 목록·경고를 화면에서 쓴다)
    parsed: Any = None

    def extend(self, other: "Proposal") -> "Proposal":
        self.ops.extend(other.ops)
        self.rejected.extend(other.rejected)
        return self


# --------------------------------------------------------------------------- #
# L0 — 수집: 조문을 불변 앵커와 함께 적재한다
# --------------------------------------------------------------------------- #
def provision_uuid(doc_id: str, anchor: str) -> str:
    """조문 앵커. 문서 안에서의 **절 경로**에서 한 번만 유도하고 그 뒤로는 바뀌지 않는다.

    번호 하나(`제1조`)로 유도하면 안 된다. 실제 규정 문서는 절마다 조 번호가 1부터
    다시 시작해서 같은 문서 안에 "제1조" 가 열 개 넘게 있다 — 실측으로 14개였다.
    그래서 앵커는 `제2장/제2절/제1조` 같은 경로에서 유도한다.

    개정으로 번호가 밀리거나 조문이 분화하면 새 UUID 를 부여하고 SPLIT_INTO 로 잇는다.
    번호를 식별자로 계속 쓰면 개정 한 번에 전 매핑이 깨진다 — 이 프로젝트의
    단일 실패 지점이다.
    """
    return f"{_slug(doc_id)}-{digest(anchor)[:10]}"


#: 조문 제목은 보통 괄호 안에 있다 — "(목적) 본 규정은 …"
_TITLE_RE = re.compile(r"^\s*[(（]([^)）]{1,60})[)）]")


def _provision_title(text: str, fallback: str) -> str:
    m = _TITLE_RE.match(text)
    return m.group(1).strip() if m else (text[:60].strip() or fallback)


def ingest_regulation(
    store: Store,
    *,
    regulation_uuid: str,
    name: str,
    issuer: str,
    doc_id: str = "",
    text: str = "",
    path: str | Path | None = None,
    effective_from: str = "",
    source_url: str = "",
) -> Proposal:
    """규제 문서 → Regulation + Provision 제안. LLM 을 쓰지 않는다.

    `path` 를 주면 docx·xlsx·pdf 를 파싱하고, `text` 를 주면 그대로 쓴다.
    어느 쪽이든 파서가 문서ID + 문자 오프셋을 부여하고, 그 오프셋이 뒤에 오는
    모든 근거의 기준 좌표가 된다.
    """
    if path is not None:
        parsed = docparse.parse(path, doc_id=doc_id or None)
    elif text:
        parsed = docparse.ParsedDoc(doc_id, doc_id, "txt", text)
        parsed.sections = docparse.detect_sections(text)
    else:
        raise ValueError("path 나 text 중 하나는 있어야 한다")

    doc_id = parsed.doc_id
    store.put_document(doc_id, parsed.text)

    ops: list[dict[str, Any]] = [
        create_node("Regulation", {
            "uuid": regulation_uuid, "name": name, "issuer": issuer,
            "effective_from": effective_from, "source_url": source_url,
            "doc_no": doc_id, "status": "active",
        }, derivation="collected")
    ]
    reg_id = node_id("Regulation", uuid=regulation_uuid)

    articles = [s for s in parsed.sections if _ARTICLE_RE.match(s.number)]
    for section in articles:
        uuid = provision_uuid(doc_id, section.number_path)
        span = Span.of(doc_id, parsed.text, section.start, section.end,
                       section=section.number_path)
        body = parsed.text[section.start:section.end].strip()
        ops.append(create_node("Provision", {
            "uuid": uuid,
            "regulation_uuid": regulation_uuid,
            "number": section.number,
            "title": _provision_title(section.title, section.number),
            "text": body,
            "anchor_path": section.number_path,
            "effective_from": effective_from,
            "doc_id": doc_id,
            "status": "active",
        }, spans=[span.to_dict()], derivation="collected"))
        ops.append(create_edge(
            "HAS_PROVISION", reg_id, node_id("Provision", uuid=uuid),
            derivation="collected",
        ))

    note = f"{doc_id}: 조문 {len(articles)}건 수집"
    if parsed.warnings:
        note += " — " + "; ".join(parsed.warnings)
    return Proposal(ops=ops, note=note, parsed=parsed)


_ARTICLE_RE = re.compile(r"^제\s*\d+\s*조")


# --------------------------------------------------------------------------- #
# 서식 → 구성 검토 절차 / 작업물 → 증적
# --------------------------------------------------------------------------- #
def propose_section_procedure(
    control_code: str,
    template_path: str | Path,
    *,
    seq: str = "S1",
    max_level: int = 2,
) -> Proposal:
    """회사 서식에서 필수 절을 뽑아 구성 검토 절차를 제안한다.

    체크리스트를 손으로 옮겨 적지 않는다. 서식이 개정되면 이 명령을 다시 돌려
    새 ChangeSet 을 올리면 되고, 그 변경은 임계치 변경과 같은 G3 로 결재된다.
    """
    from . import template as tpl

    parsed = docparse.parse(template_path)
    required = tpl.required_sections(parsed, max_level=max_level)
    ops = [
        create_node("TestProcedure", {
            "control_code": control_code,
            "seq": seq,
            "kind": "section",
            "sections": [r.label for r in required],
            "template_doc": parsed.source,
            "status": "active",
        }, derivation="human"),
        create_edge(
            "VERIFIED_BY", node_id("Control", code=control_code),
            node_id("TestProcedure", control_code=control_code, seq=seq),
            derivation="human",
        ),
    ]
    return Proposal(
        ops=ops, parsed=parsed,
        note=f"{parsed.source}: 필수 절 {len(required)}개 → {control_code} 구성 검토 절차",
    )


def ingest_work_product(
    store: Store,
    path: str | Path,
    *,
    evidence_uuid: str,
    title: str = "",
    evidence_kind: str = "",
    doc_id: str = "",
    sign_yn: bool = False,
    signer: str = "",
    valid_from: str = "",
    valid_to: str = "",
    control_code: str = "",
    service_uuid: str = "",
    for_required: str = "",
) -> Proposal:
    """직원 작업물(docx·xlsx·pdf) → 증적 제안.

    절 목록과 자리표시자를 **적재 시점에** 계산해 노드에 박아 둔다. 판정은 그래프
    조회만으로 끝나야 재현되기 때문이다 — 판정할 때마다 문서를 다시 읽으면
    파서를 고치는 순간 과거 판정이 조용히 달라진다.
    """
    from . import template as tpl

    parsed = docparse.parse(path, doc_id=doc_id or None)
    store.put_document(parsed.doc_id, parsed.text)
    placeholders = tpl.find_placeholders(parsed)

    span = _opening_span(parsed)
    props: dict[str, Any] = {
        "uuid": evidence_uuid,
        "title": title or parsed.source,
        "evidence_kind": evidence_kind or parsed.kind,
        "required_yn": False,
        "doc_ref": parsed.doc_id,
        "doc_kind": parsed.kind,
        "sha256": parsed.sha256[:32],
        "sign_yn": sign_yn,
        "signer": signer,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "sections": [s.label for s in parsed.sections],
        "placeholders": [
            {"why": p["why"], "section": p["section"], "quote": p["quote"]}
            for p in placeholders
        ],
        "status": "active",
    }
    ops = [create_node("Evidence", props, spans=[span.to_dict()],
                       derivation="collected")]

    if control_code and service_uuid:
        ops.append(create_edge(
            "SATISFIED_BY",
            node_id("Control", code=control_code),
            node_id("Evidence", uuid=evidence_uuid),
            {"service_uuid": service_uuid,
             "for_required": for_required or node_id("Evidence", uuid=evidence_uuid)},
            spans=[span.to_dict()], derivation="collected",
        ))

    note = (f"{parsed.source}: 절 {len(parsed.sections)}개"
            f" · 자리표시자 {len(placeholders)}건")
    if parsed.warnings:
        note += " — " + "; ".join(parsed.warnings)
    return Proposal(ops=ops, parsed=parsed, note=note)


def _opening_span(parsed: docparse.ParsedDoc) -> Span:
    """문서의 첫 절(보통 표제부)을 근거 스팬으로. 원문에서 잘라 만든다."""
    if parsed.sections:
        first = parsed.sections[0]
        end = min(first.end, first.start + 400)
        return Span.of(parsed.doc_id, parsed.text, first.start, end,
                       section=first.label)
    end = min(len(parsed.text), 300)
    return Span.of(parsed.doc_id, parsed.text, 0, end, section="본문")


# --------------------------------------------------------------------------- #
# L1 — 이해: 의무를 뽑되, 근거는 우리가 대조한다
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = """너는 규제 문서에서 '의무'를 추출하는 도구다.

지켜야 할 것:
1. 판정하지 마라. 어떤 조직이 이 의무를 준수했는지는 네 일이 아니다.
2. 문서에 없는 것을 만들지 마라. 모든 항목은 원문 문장을 **글자 그대로** 인용해야 한다.
   인용문은 원문에서 그대로 찾을 수 있어야 하며, 줄임표나 요약을 넣으면 폐기된다.
3. 강제력을 부풀리지 마라. '노력하여야 한다'는 권고이지 필수가 아니다.
   원문 어미가 '하여야 한다/해야 한다/아니 된다'이면 필수, '권고/바람직/노력'이면 권고다.
4. 확신할 수 없으면 그 항목을 빼라. 빠진 것은 사람이 채우지만, 틀린 것은 감사에서 문제가 된다.

출력은 JSON 배열 하나뿐이다. 설명을 붙이지 마라.
[
  {"title": "의무를 한 문장으로", "level": "필수" 또는 "권고",
   "quote": "원문에서 그대로 옮긴 근거 문장",
   "mapping_type": "equivalent-to|subset-of|superset-of|intersects-with"}
]
"""

USER_TEMPLATE = """다음은 「{regulation}」 {number} {title} 의 원문이다.

---
{text}
---

이 조문에서 도출되는 의무를 JSON 배열로 뽑아라."""


def propose_obligations(
    store: Store,
    provisions: list[dict[str, Any]],
    *,
    provider: Any = None,
    regulation_name: str = "",
    max_items: int = 6,
) -> Proposal:
    """조문 → 의무 제안.

    provider 가 없으면 결정론적 기준선 추출기를 쓴다. 어미로 문장을 고르는 단순한
    규칙이지만 근거 대조를 똑같이 거치므로, LLM 없이도 파이프라인 전체를 돌릴 수 있다.
    """
    result = Proposal()
    documents = store.documents()

    for prv in provisions:
        props = prv["props"] if "props" in prv else prv
        doc_id = str(props.get("doc_id", ""))
        text = documents.get(doc_id)
        if text is None:
            result.rejected.append({"provision": props.get("uuid"),
                                    "reason": f"원문 없음: {doc_id}"})
            continue

        if provider is None:
            items = _baseline_obligations(str(props.get("text", "")), max_items)
        else:
            items = _ask(provider, props, regulation_name)

        prv_id = node_id("Provision", uuid=str(props.get("uuid")))
        for item in items[:max_items]:
            quote = str(item.get("quote", "")).strip()
            title = str(item.get("title", "")).strip()
            level = str(item.get("level", "")).strip()
            if not quote or not title or level not in ("필수", "권고"):
                result.rejected.append({"provision": props.get("uuid"), "item": item,
                                        "reason": "필수 항목 누락 또는 알 수 없는 강제력"})
                continue
            found = locate_quote(text, quote)
            if found is None:
                # 원문에 없는 문장 — 지어낸 근거다. 여기서 버린다.
                result.rejected.append({"provision": props.get("uuid"), "item": item,
                                        "reason": "인용문을 원문에서 찾을 수 없다 (근거 미실재)"})
                continue
            # 스팬은 원문에서 다시 잘라 만든다 — 모델이 준 문자열을 그대로 쓰지 않는다.
            span = Span.of(doc_id, text, found[0], found[1],
                           section=str(props.get("number", "")))
            uuid = f"{props.get('uuid')}-{digest(title)[:8]}"
            result.ops.append(create_node("Obligation", {
                "uuid": uuid, "title": title, "level": level,
                "text": quote, "status": "active",
            }, spans=[span.to_dict()], derivation="llm"))
            mapping = str(item.get("mapping_type", "subset-of"))
            result.ops.append(create_edge(
                "DERIVES", prv_id, node_id("Obligation", uuid=uuid),
                {"mapping_type": mapping}, spans=[span.to_dict()], derivation="llm",
            ))
    result.note = (
        f"의무 제안 {len(result.ops) // 2} 건 / 근거 대조 탈락 {len(result.rejected)} 건"
    )
    return result


def _ask(provider: Any, props: dict[str, Any], regulation_name: str) -> list[dict[str, Any]]:
    prompt = USER_TEMPLATE.format(
        regulation=regulation_name or "규제 문서",
        number=props.get("number", ""), title=props.get("title", ""),
        text=props.get("text", ""),
    )
    try:
        raw = provider.complete(SYSTEM_PROMPT, prompt)
    except Exception:      # noqa: BLE001 - 공급자 장애가 파이프라인을 죽이면 안 된다
        return []
    return _parse_json_array(raw)


def _parse_json_array(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [p for p in payload if isinstance(p, dict)]


#: 문장 끝 어미로 의무 문장을 고른다. 판단이 아니라 형태 매칭이다.
#: 줄바꿈으로 자르지 않는다 — 법령 원문은 한 문장이 여러 줄에 걸치는 것이 보통이고,
#: 줄 단위로 자르면 인용문이 문장 조각이 되어 근거로서 쓸모가 없어진다.
_SENTENCE_RE = re.compile(r"[^.。]+[.。]")


def _baseline_obligations(text: str, limit: int) -> list[dict[str, Any]]:
    """LLM 없는 기준선 — 강제력 어미를 가진 문장을 그대로 의무로 올린다."""
    out: list[dict[str, Any]] = []
    for match in _SENTENCE_RE.finditer(text):
        sentence = match.group().strip()
        if len(sentence) < 10:
            continue
        force = force_of(sentence)
        if force == FORCE_MUST:
            level = "필수"
        elif force == FORCE_SHOULD:
            level = "권고"
        else:
            continue
        title = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩]\s*", "", sentence)
        title = re.sub(r"\s+", " ", title).strip()[:80]
        out.append({
            "title": title, "level": level, "quote": sentence,
            "mapping_type": "subset-of",
        })
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------- #
# 작업물 → 증적 연결 제안 (sLM)
# --------------------------------------------------------------------------- #
LINK_SYSTEM = """너는 사내 문서가 어떤 통제의 증적인지 **후보를 제안**하는 도구다.

지켜야 할 것:
1. 판정하지 마라. 이 문서가 통제를 충족하는지는 네 일이 아니다.
   네가 답할 것은 "이 문서가 그 통제의 증적으로 제출될 만한 종류인가" 뿐이다.
2. 근거는 문서 원문에서 **글자 그대로** 인용하라. 요약하거나 다듬으면 폐기된다.
3. 확신할 수 없으면 그 후보를 빼라. 사람이 나중에 붙이는 비용보다,
   틀린 연결이 승인 그래프에 들어가는 비용이 훨씬 크다.
4. 목록에 없는 통제 코드를 지어내지 마라.

출력은 JSON 배열 하나뿐이다. 설명을 붙이지 마라.
[{"control": "통제코드", "quote": "원문에서 그대로 옮긴 근거 문장"}]
"""

LINK_TEMPLATE = """[문서]
파일: {source}
절 목록:
{sections}

본문 앞부분:
---
{head}
---

[증적을 기다리는 통제]
{controls}

이 문서가 증적이 될 만한 통제를 JSON 배열로 제안하라."""


def propose_evidence_links(
    store: Store,
    parsed: docparse.ParsedDoc,
    graph: Any,
    *,
    service_uuid: str,
    provider: Any = None,
    evidence_uuid: str = "",
    head_chars: int = 1800,
) -> Proposal:
    """작업물이 어느 통제의 증적인지 sLM 이 **제안**한다.

    지금은 사람이 "별첨05가 HI-19의 증적이다" 를 손으로 붙인다. 그 일을 모델이
    대신 제안하고, 근거 대조와 커밋 결재라는 같은 게이트를 지난다. 모델이 통제
    코드를 지어내면 목록에 없으므로 떨어지고, 근거를 지어내면 원문에서 찾을 수
    없으므로 떨어진다.
    """
    result = Proposal(parsed=parsed)
    controls = _waiting_controls(graph)
    if not controls:
        result.note = "증적을 기다리는 통제가 없다"
        return result

    known = {c["code"] for c in controls}
    items: list[dict[str, Any]] = []
    if provider is not None:
        prompt = LINK_TEMPLATE.format(
            source=parsed.source,
            sections="\n".join(f"- {s.label}" for s in parsed.sections[:25]) or "- (없음)",
            head=parsed.text[:head_chars],
            controls="\n".join(
                f"- {c['code']}: {c['title']} (요구 증적: {c['evidence'] or '미정'})"
                for c in controls
            ),
        )
        try:
            items = _parse_json_array(provider.complete(LINK_SYSTEM, prompt))
        except Exception:      # noqa: BLE001 - 공급자 장애가 파이프라인을 죽이면 안 된다
            items = []

    for item in items:
        code = str(item.get("control", "")).strip()
        quote = str(item.get("quote", "")).strip()
        if code not in known:
            result.rejected.append({"item": item, "reason": f"목록에 없는 통제 코드: {code}"})
            continue
        found = locate_quote(parsed.text, quote)
        if found is None:
            result.rejected.append({"item": item, "reason": "인용문을 원문에서 찾을 수 없다 (근거 미실재)"})
            continue
        span = Span.of(parsed.doc_id, parsed.text, found[0], found[1],
                       section=_section_at(parsed, found[0]))
        target = evidence_uuid or parsed.doc_id
        required = next((c["required_id"] for c in controls if c["code"] == code), "")
        result.ops.append(create_edge(
            "SATISFIED_BY",
            node_id("Control", code=code),
            node_id("Evidence", uuid=target),
            {"service_uuid": service_uuid,
             "for_required": required or node_id("Evidence", uuid=target)},
            spans=[span.to_dict()], derivation="llm",
        ))

    result.note = (f"{parsed.source}: 증적 연결 제안 {len(result.ops)}건"
                   f" / 탈락 {len(result.rejected)}건")
    return result


def _waiting_controls(graph: Any) -> list[dict[str, Any]]:
    """요구 증적이 정의된 통제 목록. 모델에게는 이 목록만 보여 준다."""
    out: list[dict[str, Any]] = []
    for ctrl in graph.of_type("Control"):
        required = [
            e["target"] for e in graph.out_edges(ctrl["id"], "PRODUCES")
            if graph.props(e["target"]).get("required_yn") is True
        ]
        titles = [str(graph.props(r).get("title", "")) for r in required]
        out.append({
            "code": str(ctrl["props"].get("code", "")),
            "title": str(ctrl["props"].get("title", "")),
            "evidence": ", ".join(t for t in titles if t),
            "required_id": required[0] if required else "",
        })
    return out


def _section_at(parsed: docparse.ParsedDoc, offset: int) -> str:
    for s in parsed.sections:
        if s.start <= offset < s.end:
            return s.number_path or s.label
    return "본문"


# --------------------------------------------------------------------------- #
# LLMWiki 연계 — 증적을 만드는 것은 결국 운영 프로그램이다
# --------------------------------------------------------------------------- #
def propose_system_functions(
    index: Any, *, project_id: str = "default", system: str = "",
    only_layers: list[str] | None = None,
) -> Proposal:
    """LLMWiki 가 정적 분석으로 뽑은 Program → SystemFunction 제안.

    `program_ref` 에 LLMWiki 온톨로지의 Program 노드 ID 를 그대로 넣는다.
    두 그래프를 한 저장소에 합치지 않고 참조로만 잇는다 — 규제 그래프가
    소스 분석 주기에 끌려다니지 않게 하기 위해서다.
    """
    ops: list[dict[str, Any]] = []
    for program in getattr(index, "programs", []):
        if only_layers and program.layer not in only_layers:
            continue
        ops.append(create_node("SystemFunction", {
            "key": f"llmwiki:{program.id}",
            "name": program.name,
            "system": system or program.layer or getattr(index, "project", "운영시스템"),
            "kind": "application",
            "program_ref": f"prog:{project_id}/{program.id}",
            "status": "active",
        }, derivation="collected"))
    return Proposal(ops=ops, note=f"운영 프로그램 {len(ops)} 건을 증적 생산 기능으로 제안")


def link_evidence_to_function(evidence_uuid: str, function_key: str) -> dict[str, Any]:
    return create_edge(
        "COLLECTED_FROM",
        node_id("Evidence", uuid=evidence_uuid),
        node_id("SystemFunction", key=function_key),
        derivation="collected",
    )


# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9가-힣]+", "-", text).strip("-").lower()[:40]
