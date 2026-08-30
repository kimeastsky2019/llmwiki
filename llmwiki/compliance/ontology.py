"""규제 지식그래프 온톨로지 — 확정 스키마 v1.0.0.

이 파일이 스키마의 **단일 원본**이다. 문서가 아니라 코드로 두고 테스트로 고정한다
(`llmwiki/ontology.py` 와 같은 이유다 — 문서로만 두면 코드가 먼저 움직이고 낡는다).

세 개의 헌법
------------
1) **근거 없는 사실 금지** — 문서에서 온 노드·엣지는 원문 스팬을 반드시 갖는다.
   `requires_span=True` 로 선언하고 `verify.validate_graph` 가 강제한다.
   예외는 문서에서 온 사실이 아닌 것뿐이다: 조직이 등록한 Service·Agent·RuleSet,
   룰이 산출한 Assessment.
2) **삭제 없음** — 물리 삭제가 없다. `status="obsolete"` + `replaced_by` 만 허용한다.
   저장소(`store`)가 append-only 저널이라 애초에 삭제 연산이 없다.
3) **판정 재현성** — 모든 Assessment 는 온톨로지·룰셋·기준·조문 **4개 버전**을
   참조한다. 1년 뒤에도 당시 판정을 그대로 재현할 수 있어야 한다.

단일 실패 지점 — 조문 앵커
--------------------------
법령이 개정되며 "제13조" 가 "제13조의2" 로 분화되거나 번호가 밀리면, 조문 번호를
식별자로 쓴 매핑은 전부 깨진다. 그래서 Provision 의 ID 는 **불변 UUID** 이고
번호(`number`)는 속성이다. 분화는 `SPLIT_INTO` 계보로 잇는다.
`anchor=True` 인 노드 타입은 id_parts 가 반드시 ("uuid",) 여야 한다 —
테스트가 이것을 고정한다.

권한 3분할
----------
제안(sLM) / 판정(룰) / 확정(사람) 을 스키마 레벨에서 가른다.
`NodeType.llm_proposable` 이 False 인 타입은 SoftwareAgent 가 제안할 수 없다.
Assessment 가 대표적이다 — 모델은 판정 노드를 만들 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

COMPLIANCE_ONTOLOGY_VERSION = "1.0.0"

#: collected — 수집기가 문서·시스템에서 기계적으로 읽은 사실
#: llm       — sLM 이 문서에서 뽑아 제안한 사실 (승인 전에는 그래프에 없다)
#: human     — 사람이 등록·확정한 사실
#: rule      — 결정론적 룰이 산출한 것 (판정)
Derivation = Literal["collected", "llm", "human", "rule"]

DERIVATIONS: tuple[str, ...] = ("collected", "llm", "human", "rule")

# --------------------------------------------------------------------------- #
# 닫힌 집합
# --------------------------------------------------------------------------- #
#: 자동화 수준. L3 는 정성 판단이라 룰이 판정하지 않고 항상 사람에게 넘긴다.
AUTO_LEVELS: tuple[str, ...] = ("L1", "L2", "L3")

#: 의무의 강제력. 화면·API 로 그대로 나가는 값이라 영어로 둔다.
MANDATORY = "mandatory"
RECOMMENDED = "recommended"
OBLIGATION_LEVELS: tuple[str, ...] = (MANDATORY, RECOMMENDED)

#: 평가 절차의 종류.
#: section 은 "서식이 요구한 절이 작업물에 있는가" — 내용 평가가 아니라 구성 검토다.
PROCEDURE_KINDS: tuple[str, ...] = ("evidence", "metric", "section", "qualitative")

#: 지표 비교 연산자 (룰이 결정론적으로 평가한다)
OPERATORS: tuple[str, ...] = (">=", ">", "<=", "<", "==", "!=")

#: NIST OSCAL Control Mapping 의 집합론 술어.
#: 이진(매핑됨/안됨)으로 만들면 "부분 충족" 을 표현할 수 없고,
#: 그러면 커버리지 갭 분석이 무의미해진다.
MAPPING_TYPES: tuple[str, ...] = (
    "equivalent-to", "subset-of", "superset-of", "intersects-with", "no-relationship",
)

#: Agent 의 종류. SoftwareAgent 는 제안만 할 수 있다.
AGENT_KINDS: tuple[str, ...] = ("Person", "Organization", "SoftwareAgent")

#: 노드의 생애 상태. 삭제가 없으므로 obsolete 로만 내린다.
NODE_STATUSES: tuple[str, ...] = ("active", "amending", "obsolete")

# --- 판정 ------------------------------------------------------------------ #
SATISFIED = "SATISFIED"
PARTIAL = "PARTIAL"
UNSATISFIED = "UNSATISFIED"
NOT_APPLICABLE = "NOT_APPLICABLE"
DEFERRED = "DEFERRED"

VERDICTS: tuple[str, ...] = (SATISFIED, PARTIAL, UNSATISFIED, NOT_APPLICABLE, DEFERRED)

#: 판정의 결재 상태. 노드 생애 상태(NODE_STATUSES)와는 다른 축이다 —
#: 룰이 낸 판정은 사람이 서명하기 전까지 provisional 로 남는다.
#: 그래프에 저장되는 값이므로 영어로 둔다.
PROVISIONAL = "provisional"
CONFIRMED = "confirmed"
DECISION_STATUSES: tuple[str, ...] = (PROVISIONAL, CONFIRMED)

#: 화면에 그대로 찍히는 판정 라벨.
VERDICT_LABELS: dict[str, str] = {
    SATISFIED: "Satisfied",
    PARTIAL: "Partially satisfied",
    UNSATISFIED: "Not satisfied",
    NOT_APPLICABLE: "Not applicable",
    DEFERRED: "Deferred to reviewer",
}

#: 판단 유보 트리거 — 정밀도 우선.
#: 커버리지를 늘리려다 심사자가 물량에 압도되면 형식 승인이 발생하고,
#: 그것은 통제 실효성 자체를 무너뜨린다. 애매하면 사람에게 넘긴다.
DEFERRAL_TRIGGERS: dict[str, str] = {
    "QUALITATIVE": "Control is auto_level L3 — needs human judgement",
    "PARTIAL_EVIDENCE": "Only some required evidence is present — sufficiency is a "
                        "judgement call",
    "THRESHOLD_UNDEFINED": "Metric exists but no threshold is defined",
    "METRIC_MISSING": "Threshold is defined but no measurement was found",
    "EVIDENCE_EXPIRING": "Evidence expires within 30 days",
    "PROVISION_AMENDING": "Cited provision is being amended — the standard itself is "
                          "in flux",
    "VERDICT_FLIPPED": "Verdict flipped since the previous run — the reason for the "
                       "change needs checking",
    "CITATION_WEAK": "Citation-strength check failed — the claim is stronger than the "
                     "quoted text supports",
    "TEMPLATE_UNFILLED": "Template placeholders are still in place — looks unfilled, "
                         "but may be sample text, so a human must confirm",
    "DOC_CONFLICT": "Documents asserting the same value disagree — a human decides "
                    "which one holds",
}

#: 증적 만료 임박 판정 기준 (일)
EXPIRY_WINDOW_DAYS = 30


# --------------------------------------------------------------------------- #
# 스키마 정의
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NodeType:
    name: str
    prefix: str
    ko: str
    id_parts: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    derivation: Derivation = "collected"
    #: True 면 ID 가 불변 UUID 다. 법령 번호처럼 바뀌는 값을 ID 로 쓰지 않는다.
    anchor: bool = False
    #: True 면 문서에서 온 사실이라 원문 스팬이 필수다.
    requires_span: bool = False
    #: False 면 SoftwareAgent(sLM) 가 제안할 수 없다 — 권한 3분할.
    llm_proposable: bool = True
    #: True 면 제안본에만 존재하고 승인 그래프에는 절대 들어가지 않는다.
    staging: bool = False
    note: str = ""

    @property
    def properties(self) -> tuple[str, ...]:
        return self.required + self.optional


@dataclass(frozen=True)
class EdgeType:
    name: str
    ko: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    cardinality: str
    derivation: Derivation = "collected"
    properties: tuple[str, ...] = ()
    #: 같은 (타입, 출발, 도착) 이라도 이 속성들이 다르면 다른 엣지다.
    #: 예: SATISFIED_BY 는 서비스마다 따로 존재한다.
    key_props: tuple[str, ...] = ()
    requires_span: bool = False
    llm_proposable: bool = True
    staging: bool = False
    note: str = ""


NODE_TYPES: dict[str, NodeType] = {
    n.name: n
    for n in (
        NodeType(
            name="Regulation", prefix="reg", ko="법령·가이드라인",
            id_parts=("uuid",),
            required=("uuid", "name", "issuer"),
            optional=("doc_no", "effective_from", "effective_to", "source_url",
                      "status", "replaced_by"),
            anchor=True, requires_span=False,
            note="규제 문서 한 건. 조문은 Provision 으로 쪼갠다.",
        ),
        NodeType(
            name="Provision", prefix="prv", ko="조문",
            id_parts=("uuid",),
            required=("uuid", "regulation_uuid", "number", "title"),
            optional=("text", "effective_from", "effective_to", "status",
                      "replaced_by", "doc_id", "note"),
            anchor=True, requires_span=True,
            note="★ 단일 실패 지점. number 는 속성이지 ID 가 아니다. "
                 "개정으로 분화하면 SPLIT_INTO 로 잇는다.",
        ),
        NodeType(
            name="Obligation", prefix="obl", ko="의무",
            id_parts=("uuid",),
            required=("uuid", "title", "level"),
            optional=("text", "status", "replaced_by", "note"),
            anchor=True, requires_span=True,
            note=f"level 은 {OBLIGATION_LEVELS} 중 하나. 인용 강도 검증의 대상이다.",
        ),
        NodeType(
            name="Control", prefix="ctrl", ko="통제",
            id_parts=("code",),
            required=("code", "title", "auto_level"),
            # title_en: 화면 언어 전환용 영문 제목. 사실이 아니라 표시라서
            # 없어도 되고, 없으면 화면은 title 을 그대로 쓴다.
            optional=("category", "owner", "status", "replaced_by", "note",
                      "title_en"),
            derivation="human",
            note=f"auto_level 은 {AUTO_LEVELS}. 내부 설계 산출물이라 코드가 곧 ID 다.",
        ),
        NodeType(
            name="TestProcedure", prefix="tp", ko="평가 절차",
            id_parts=("control_code", "seq"),
            required=("control_code", "seq", "kind"),
            optional=("metric", "operator", "threshold", "unit", "sections",
                      "template_doc", "status", "replaced_by", "note"),
            derivation="human",
            note=f"kind 는 {PROCEDURE_KINDS}. threshold 가 비면 판단 유보로 간다.",
        ),
        NodeType(
            name="Evidence", prefix="evd", ko="증적",
            id_parts=("uuid",),
            required=("uuid", "title", "evidence_kind"),
            optional=("required_yn", "doc_ref", "sha256", "sign_yn", "signer",
                      "valid_from", "valid_to", "doc_kind", "sections",
                      "placeholders", "status", "replaced_by", "note"),
            anchor=True, requires_span=False,
            note="required_yn=True 는 통제가 요구하는 증적 명세, False 는 실제 제출물. "
                 "원본은 그래프 밖(WORM)에 두고 여기에는 참조와 해시만 둔다.",
        ),
        NodeType(
            name="SystemFunction", prefix="fn", ko="증적 생산 기능",
            id_parts=("key",),
            required=("key", "name", "system"),
            optional=("kind", "program_ref", "status", "replaced_by", "note"),
            derivation="collected",
            note="ITSM · Git · CI · MLOps. program_ref 는 LLMWiki 가 뽑은 "
                 "Program 노드 ID — 여기서 두 그래프가 만난다.",
        ),
        NodeType(
            name="Service", prefix="svc", ko="AI 서비스·과제",
            id_parts=("uuid",),
            required=("uuid", "name"),
            optional=("dept", "high_impact_yn", "status", "replaced_by", "note",
                      "name_en"),
            derivation="human", anchor=True, llm_proposable=False,
            note="고영향 해당 여부는 사람이 확정한다. 모델이 제안할 수 없다.",
        ),
        NodeType(
            name="Assessment", prefix="asmt", ko="판정 결과",
            id_parts=("uuid",),
            required=("uuid", "service_uuid", "control_code", "verdict",
                      "versions", "assessed_at"),
            optional=("raw_verdict", "reason", "triggers", "evidence_ids",
                      "need", "have", "as_of", "decision_status", "confirmed_by",
                      "confirmed_at", "status", "replaced_by", "note"),
            derivation="rule", anchor=True, llm_proposable=False,
            note="★ 모델은 이 노드를 만들 수 없다. versions 에 4개 버전을 담아 재현성을 준다.",
        ),
        NodeType(
            name="RuleSet", prefix="rs", ko="판정 룰셋",
            id_parts=("version",),
            required=("version", "name"),
            optional=("note", "status", "replaced_by"),
            derivation="human", llm_proposable=False,
            note="PROV 의 Plan 에 해당. 판정이 어떤 룰로 나왔는지 고정한다.",
        ),
        NodeType(
            name="Agent", prefix="agt", ko="주체",
            id_parts=("agent_id",),
            required=("agent_id", "name", "kind"),
            optional=("dept", "status", "replaced_by", "note"),
            derivation="human", llm_proposable=False,
            note=f"kind 는 {AGENT_KINDS}.",
        ),
        NodeType(
            name="ChangeSet", prefix="cs", ko="변경 제안",
            id_parts=("changeset_id",),
            required=("changeset_id", "proposer", "status"),
            optional=("source", "ops", "impact", "grade", "created_at",
                      "reviewed_by", "reviewed_at", "review_note"),
            derivation="llm", staging=True,
            note="승인 전에는 승인 그래프에 존재하지 않는다. 제안이 쌓여도 판정에 영향이 없다.",
        ),
        NodeType(
            name="RegChange", prefix="rc", ko="규제 개정 감지",
            id_parts=("change_id",),
            required=("change_id", "title", "detected_at"),
            optional=("source_url", "summary", "regulation_uuid"),
            derivation="collected", staging=True,
            note="외부 세그먼트에서 반입된다. 곧바로 기준이 되지 않고 커밋 결재 큐로 간다.",
        ),
    )
}

EDGE_TYPES: dict[str, EdgeType] = {
    e.name: e
    for e in (
        EdgeType("HAS_PROVISION", "조문 보유", ("Regulation",), ("Provision",), "1:N"),
        EdgeType(
            "DERIVES", "의무 도출", ("Provision",), ("Obligation",), "N:M",
            properties=("mapping_type",), requires_span=True,
            note=f"mapping_type 은 {MAPPING_TYPES} — 부분 충족을 표현하기 위한 집합론 술어.",
        ),
        EdgeType(
            "IMPLEMENTED_BY", "통제로 구현", ("Obligation",), ("Control",), "N:M",
            properties=("mapping_type",), derivation="human",
            note="여기가 비어 있는 의무가 곧 커버리지 갭이다.",
        ),
        EdgeType("VERIFIED_BY", "평가 절차", ("Control",), ("TestProcedure",), "1:N",
                 derivation="human"),
        EdgeType("PRODUCES", "요구 증적", ("Control",), ("Evidence",), "1:N",
                 derivation="human", note="required_yn=True 인 Evidence 만 가리킨다."),
        EdgeType("COLLECTED_FROM", "증적 출처", ("Evidence",), ("SystemFunction",), "N:1",
                 note="이 엣지가 없는 통제 = 수기 의존 = 자동화 후보."),
        EdgeType("APPLIES_TO", "적용 대상", ("Control",), ("Service",), "N:M",
                 derivation="human", properties=("reason",)),
        EdgeType(
            "SATISFIED_BY", "증적 제출", ("Control",), ("Evidence",), "N:M",
            properties=("service_uuid", "for_required"),
            key_props=("service_uuid", "for_required"), requires_span=True,
            note="서비스마다 따로 존재한다. for_required 는 어느 요구 증적을 채웠는지.",
        ),
        EdgeType("ASSESSED_AS", "판정", ("Service",), ("Assessment",), "1:N",
                 derivation="rule", llm_proposable=False),
        EdgeType("used", "prov:used", ("Assessment",), ("Evidence", "RuleSet"), "N:M",
                 derivation="rule", llm_proposable=False,
                 note="판정이 실제로 무엇을 근거로 삼았는지 (PROV 계보)."),
        EdgeType("wasAttributedTo", "prov:wasAttributedTo", ("Assessment",), ("Agent",),
                 "N:1", derivation="rule", llm_proposable=False),
        EdgeType(
            "SPLIT_INTO", "조문 분화", ("Provision",), ("Provision",), "1:N",
            note="제13조 → 제13조의2 처럼 갈라질 때의 계보. 매핑이 깨지지 않게 하는 장치.",
        ),
        EdgeType(
            "REPLACED_BY", "대체", ("Provision", "Obligation", "Control", "Evidence"),
            ("Provision", "Obligation", "Control", "Evidence"), "N:1",
            note="삭제 대신 쓰는 유일한 수단.",
        ),
        EdgeType("GENERATED", "제안 생성", ("RegChange",), ("ChangeSet",), "1:N",
                 staging=True),
    )
}


# --------------------------------------------------------------------------- #
# 식별자
# --------------------------------------------------------------------------- #
def node_id(node_type: str, **parts: Any) -> str:
    """스키마의 id_parts 순서대로 ID 를 만든다. 재실행해도 값이 같아야 한다."""
    spec = NODE_TYPES.get(node_type)
    if spec is None:
        raise KeyError(f"알 수 없는 노드 타입: {node_type}")
    missing = [p for p in spec.id_parts if parts.get(p) in (None, "")]
    if missing:
        raise ValueError(f"{node_type} ID 에 필요한 값 누락: {missing}")
    body = "/".join(str(parts[p]) for p in spec.id_parts)
    return f"{spec.prefix}:{body}"


def edge_key(edge_type: str, source: str, target: str, props: dict[str, Any]) -> str:
    """엣지의 동일성 판단 키. key_props 가 다르면 다른 엣지다."""
    spec = EDGE_TYPES.get(edge_type)
    if spec is None:
        raise KeyError(f"알 수 없는 엣지 타입: {edge_type}")
    parts = [edge_type, source, target]
    parts += [str(props.get(p, "")) for p in spec.key_props]
    return "|".join(parts)


def type_of(node_ident: str) -> str | None:
    """노드 ID 의 접두어로 타입을 되찾는다."""
    prefix = node_ident.split(":", 1)[0]
    for spec in NODE_TYPES.values():
        if spec.prefix == prefix:
            return spec.name
    return None


# --------------------------------------------------------------------------- #
# 내보내기
# --------------------------------------------------------------------------- #
def schema_dict() -> dict[str, Any]:
    """스키마 자체를 기계가 읽을 수 있는 형태로."""
    return {
        "ontology": COMPLIANCE_ONTOLOGY_VERSION,
        "derivations": list(DERIVATIONS),
        "enums": {
            "auto_level": list(AUTO_LEVELS),
            "obligation_level": list(OBLIGATION_LEVELS),
            "procedure_kind": list(PROCEDURE_KINDS),
            "operator": list(OPERATORS),
            "mapping_type": list(MAPPING_TYPES),
            "agent_kind": list(AGENT_KINDS),
            "node_status": list(NODE_STATUSES),
            "verdict": list(VERDICTS),
        },
        "verdict_labels": dict(VERDICT_LABELS),
        "deferral_triggers": dict(DEFERRAL_TRIGGERS),
        "nodes": {
            n.name: {
                "prefix": n.prefix, "ko": n.ko,
                "id_parts": list(n.id_parts),
                "required": list(n.required), "optional": list(n.optional),
                "derivation": n.derivation, "anchor": n.anchor,
                "requires_span": n.requires_span,
                "llm_proposable": n.llm_proposable, "staging": n.staging,
                "note": n.note,
            }
            for n in NODE_TYPES.values()
        },
        "edges": {
            e.name: {
                "ko": e.ko, "domain": list(e.domain), "range": list(e.range),
                "cardinality": e.cardinality, "derivation": e.derivation,
                "properties": list(e.properties), "key_props": list(e.key_props),
                "requires_span": e.requires_span,
                "llm_proposable": e.llm_proposable, "staging": e.staging,
                "note": e.note,
            }
            for e in EDGE_TYPES.values()
        },
    }
