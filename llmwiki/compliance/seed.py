"""데모 데이터 — 설정 없이 전체 흐름을 한 번 돌려 볼 수 있게 한다.

`sample/` 이 소스 분석 데모인 것과 같은 역할이다. 여기 들어 있는 규제 원문은
**실제 법령이 아니라 데모용으로 작성한 샘플**이다. 조문 형식과 어미(하여야 한다 /
노력하여야 한다)만 실제와 같게 맞춰, 조문 분할·근거 대조·인용 강도 검증이
실제로 동작하는지 볼 수 있게 했다.

시드도 커밋 결재를 거친다. 뒷문으로 그래프에 쓰지 않는다 — 게이트를 우회하는
경로를 하나라도 두면 그 경로가 결국 운영에서 쓰인다.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from . import changeset as cs
from .changeset import create_edge, create_node
from .ontology import node_id
from .propose import ingest_regulation, propose_obligations
from .spans import Span
from .store import Store

REG_DOC_ID = "sample-ai-risk-guideline-2026"
REG_UUID = "reg-ai-risk-2026"
REG_NAME = "(샘플) 금융 AI 위험관리 지침"

SEED_AGENT = {"type": "Organization", "id": "system-seed"}

#: 데모용 샘플 조문. 실제 법령 원문이 아니다.
REGULATION_TEXT = """(샘플) 금융 AI 위험관리 지침

제1조(목적) 이 지침은 금융회사가 인공지능 서비스를 도입·운영할 때 준수하여야 하는
위험관리 사항을 정함을 목적으로 한다.

제2조(정의) 이 지침에서 "고영향 인공지능"이란 개인의 권리·의무에 중대한 영향을
미칠 수 있는 인공지능 서비스를 말한다.

제3조(이해관계자 책임관계) ① 금융회사는 인공지능 서비스별로 기획·개발·운영·점검
각 단계의 이해관계자와 그 책임관계를 문서로 명시하여야 한다.
② 제1항에 따른 문서는 인공지능 거버넌스 담당자의 승인을 받아야 한다.

제4조(성능 관리) ① 금융회사는 인공지능 서비스의 성능지표를 정기적으로 측정하여야 한다.
② 성능지표가 사전에 정한 임계치에 미달하는 경우 개선 조치를 하여야 한다.
③ 금융회사는 성능지표의 산출 근거를 이용자에게 공개하도록 노력하여야 한다.

제5조(위험 점검) ① 금융회사는 고영향 인공지능 서비스에 대하여 연 1회 이상 위험
점검을 실시하여야 한다.
② 점검의 결과는 기록하고 보존하여야 한다.

제6조(설명자료) 금융회사는 이용자에게 제공하는 인공지능 설명자료를 알기 쉽게
작성하는 것이 바람직하다.
"""

#: 증적 원문 — 근거 스팬이 실재하는지 대조할 수 있어야 하므로 함께 적재한다.
EVIDENCE_DOCS: dict[str, str] = {
    "evd-hi19-svc001": (
        "책임관계 정의서 (여신심사 스코어링)\n"
        "3-2. 단계별 이해관계자와 책임관계를 아래 표와 같이 정의하고 "
        "AI거버넌스담당자의 승인을 받았다.\n"
        "승인일 2026-03-11 / 승인자 AI거버넌스담당자\n"
    ),
    "evd-pf07-svc001": (
        "성능 측정 결과서 (여신심사 스코어링)\n"
        "2026년 2분기 정기 측정 결과 AUC 0.82 로 사전에 정한 임계치를 충족하였다.\n"
    ),
    "evd-rm03-svc001": (
        "위험 점검 결과서 (여신심사 스코어링)\n"
        "2026년 연차 위험 점검을 실시하고 그 결과를 기록하였다.\n"
    ),
    "evd-mn05-svc002": (
        "모형 변경 이력 대장 (콜센터 요약 보조)\n"
        "변경 요청·승인·반영 이력을 대장에 기록하고 담당 부서장이 서명하였다.\n"
    ),
    "evd-pf07-svc002": (
        "성능 측정 결과서 (콜센터 요약 보조)\n"
        "2026년 1분기 측정 결과 요약 정확도 0.88 을 기록하였다.\n"
    ),
}

# --- 통제 · 절차 · 요구 증적 ------------------------------------------------ #
CONTROLS: list[dict[str, Any]] = [
    {"code": "HI-19", "title": "이해관계자 책임관계 명시 문서 작성", "auto_level": "L1",
     "category": "고영향 책무", "owner": "AI거버넌스담당자"},
    {"code": "PF-07", "title": "성능지표 정기 측정 및 임계치 관리", "auto_level": "L2",
     "category": "성능 KPI", "owner": "모델개발팀"},
    {"code": "RM-03", "title": "연차 위험 점검 실시 및 결과 보존", "auto_level": "L1",
     "category": "위험점검", "owner": "리스크관리부"},
    {"code": "QA-11", "title": "설명자료 적정성 판단", "auto_level": "L3",
     "category": "정성", "owner": "AI거버넌스담당자"},
    {"code": "MN-05", "title": "모형 변경 이력 관리", "auto_level": "L1",
     "category": "운영", "owner": "모델운영팀"},
    {"code": "TH-09", "title": "드리프트 감시", "auto_level": "L2",
     "category": "성능 KPI", "owner": "모델운영팀"},
]

PROCEDURES: list[dict[str, Any]] = [
    {"control_code": "HI-19", "seq": "1", "kind": "evidence"},
    {"control_code": "PF-07", "seq": "1", "kind": "evidence"},
    {"control_code": "PF-07", "seq": "2", "kind": "metric",
     "metric": "model_auc", "operator": ">=", "threshold": 0.75, "unit": ""},
    {"control_code": "RM-03", "seq": "1", "kind": "evidence"},
    {"control_code": "QA-11", "seq": "1", "kind": "qualitative"},
    {"control_code": "MN-05", "seq": "1", "kind": "evidence"},
    # ★ 임계치 미정 — EY 산출물 32개 위험 중 임계치를 가진 것은 11개(34%)뿐이었다.
    #   이런 항목은 자동 판정하지 않고 판단 유보로 넘긴다.
    {"control_code": "TH-09", "seq": "1", "kind": "metric", "metric": "drift_psi"},
]

REQUIRED_EVIDENCE: list[dict[str, Any]] = [
    {"control": "HI-19", "uuid": "req-hi19-doc", "title": "이해관계자 책임관계 정의서",
     "evidence_kind": "책임관계정의서", "function": "gov-doc-repo"},
    {"control": "PF-07", "uuid": "req-pf07-report", "title": "성능 측정 결과서",
     "evidence_kind": "성능측정결과서", "function": "mlops-metric-store"},
    {"control": "RM-03", "uuid": "req-rm03-report", "title": "위험 점검 결과서",
     "evidence_kind": "위험점검결과서", "function": "gov-doc-repo"},
    {"control": "RM-03", "uuid": "req-rm03-log", "title": "위험 점검 이력",
     "evidence_kind": "점검이력", "function": "itsm-change"},
    # ★ 증적 생산 기능이 없다 = 수기 의존 = 자동화 후보
    {"control": "MN-05", "uuid": "req-mn05-log", "title": "모형 변경 이력 대장",
     "evidence_kind": "변경이력대장", "function": ""},
]

SYSTEM_FUNCTIONS: list[dict[str, Any]] = [
    {"key": "gov-doc-repo", "name": "거버넌스 문서 저장소", "system": "ITSM",
     "kind": "repository"},
    {"key": "mlops-metric-store", "name": "MLOps 지표 저장소", "system": "MLOps",
     "kind": "metric-store"},
    {"key": "itsm-change", "name": "변경관리 시스템", "system": "ITSM", "kind": "workflow"},
]

SERVICES: list[dict[str, Any]] = [
    {"uuid": "svc-001", "name": "여신심사 스코어링", "dept": "여신기획부",
     "high_impact_yn": True},
    {"uuid": "svc-002", "name": "콜센터 요약 보조", "dept": "고객지원부",
     "high_impact_yn": False},
]

APPLIES: list[tuple[str, str]] = [
    ("HI-19", "svc-001"), ("PF-07", "svc-001"), ("RM-03", "svc-001"),
    ("QA-11", "svc-001"), ("MN-05", "svc-001"), ("TH-09", "svc-001"),
    ("PF-07", "svc-002"), ("MN-05", "svc-002"),
]

AGENTS: list[dict[str, Any]] = [
    {"agent_id": "rule-engine", "name": "판정 룰 엔진", "kind": "SoftwareAgent",
     "dept": "시스템"},
    {"agent_id": "gov-officer", "name": "AI거버넌스담당자", "kind": "Person",
     "dept": "AI거버넌스"},
    {"agent_id": "ai-governance", "name": "AI거버넌스협의체", "kind": "Organization"},
    {"agent_id": "system-seed", "name": "초기 적재", "kind": "Organization"},
]

RULESET_VERSION = "1.0.0"


def seed(store: Store, *, today: date | None = None) -> dict[str, Any]:
    """데모 데이터를 커밋 결재 경로로 적재한다."""
    today = today or date.today()
    log: list[str] = []

    def commit(ops: list[dict[str, Any]], proposer: dict[str, str], note: str) -> None:
        change = cs.stage(store, ops, proposer=proposer, source={"type": "seed", "id": note})
        if change.status != cs.PENDING:
            issues = "; ".join(i["message"] for i in change.checks.get("issues", []))
            raise RuntimeError(f"시드 게이트 실패 ({note}): {issues}")
        cs.approve(store, change.changeset_id, approver="system-seed", note=note)
        log.append(f"{change.changeset_id} [{change.grade}] {note} — ops {len(change.ops)}")

    # L0 — 규제 원문 수집
    for doc_id, text in EVIDENCE_DOCS.items():
        store.put_document(doc_id, text)
    intake = ingest_regulation(
        store, doc_id=REG_DOC_ID, text=REGULATION_TEXT, regulation_uuid=REG_UUID,
        name=REG_NAME, issuer="(샘플) 감독기관", effective_from="2026-06-01",
    )
    commit(intake.ops, {"type": "SoftwareAgent", "id": "collector-v1"}, "규제 원문 수집")

    # L1 — 의무 제안 (LLM 없이 기준선 추출기)
    graph = store.approved()
    provisions = [n for n in graph.of_type("Provision")]
    proposal = propose_obligations(store, provisions, regulation_name=REG_NAME)
    commit(proposal.ops, {"type": "SoftwareAgent", "id": "slm-extract-v1"}, "의무 추출 제안")
    log.append(proposal.note)

    # 통제 · 절차 · 요구 증적 · 시스템 기능 · 룰셋 · 주체
    ops: list[dict[str, Any]] = []
    for agent in AGENTS:
        ops.append(create_node("Agent", {**agent, "status": "active"}, derivation="human"))
    for fn in SYSTEM_FUNCTIONS:
        ops.append(create_node("SystemFunction", {**fn, "status": "active"},
                               derivation="collected"))
    for control in CONTROLS:
        ops.append(create_node("Control", {**control, "status": "active"},
                               derivation="human"))
    for proc in PROCEDURES:
        ops.append(create_node("TestProcedure", {**proc, "status": "active"},
                               derivation="human"))
        ops.append(create_edge(
            "VERIFIED_BY", node_id("Control", code=proc["control_code"]),
            node_id("TestProcedure", control_code=proc["control_code"], seq=proc["seq"]),
            derivation="human",
        ))
    for req in REQUIRED_EVIDENCE:
        ops.append(create_node("Evidence", {
            "uuid": req["uuid"], "title": req["title"],
            "evidence_kind": req["evidence_kind"], "required_yn": True,
            "status": "active",
        }, derivation="human"))
        ops.append(create_edge(
            "PRODUCES", node_id("Control", code=req["control"]),
            node_id("Evidence", uuid=req["uuid"]), derivation="human",
        ))
        if req["function"]:
            ops.append(create_edge(
                "COLLECTED_FROM", node_id("Evidence", uuid=req["uuid"]),
                node_id("SystemFunction", key=req["function"]), derivation="collected",
            ))
    ops.append(create_node("RuleSet", {
        "version": RULESET_VERSION, "name": "기본 판정 룰셋",
        "standard_version": "2026.08", "status": "active",
    }, derivation="human"))
    commit(ops, SEED_AGENT, "통제·절차·요구증적·룰셋 등록")

    # 의무 → 통제 매핑 (사람이 정한다)
    graph = store.approved()
    # 근거 문장(text)으로 매칭한다. 제목은 잘려 있을 수 있어 기준으로 삼지 않는다.
    mapping: list[tuple[str, str, str]] = [
        ("책임관계를 문서로 명시", "HI-19", "equivalent-to"),
        ("성능지표를 정기적으로 측정", "PF-07", "subset-of"),
        ("임계치에 미달", "PF-07", "subset-of"),
        ("점검을 실시", "RM-03", "subset-of"),
        ("기록하고 보존", "RM-03", "subset-of"),
        ("설명자료", "QA-11", "intersects-with"),
    ]
    ops = []
    linked: set[str] = set()
    for keyword, code, mapping_type in mapping:
        for obl in graph.of_type("Obligation"):
            body = " ".join(str(obl["props"].get("text", "")).split())
            if keyword not in body:
                continue
            key = f"{obl['id']}->{code}"
            if key in linked:
                continue
            linked.add(key)
            ops.append(create_edge(
                "IMPLEMENTED_BY", obl["id"], node_id("Control", code=code),
                {"mapping_type": mapping_type}, derivation="human",
            ))
    commit(ops, SEED_AGENT, "의무 → 통제 매핑")

    # 서비스 · 적용 · 제출 증적
    ops = []
    for svc in SERVICES:
        ops.append(create_node("Service", {**svc, "status": "active"}, derivation="human"))
    for code, svc_uuid in APPLIES:
        ops.append(create_edge(
            "APPLIES_TO", node_id("Control", code=code),
            node_id("Service", uuid=svc_uuid), {"reason": "적용 범위 판단(사람)"},
            derivation="human",
        ))
    ops.extend(_submitted_evidence(store, today))
    commit(ops, SEED_AGENT, "서비스 등록 및 증적 제출")

    # 지표 측정값 · 골드셋
    store.write_json("metrics.json", {
        "svc-001": {"model_auc": 0.82, "drift_psi": 0.12},
        # svc-002 는 측정값이 없다 — METRIC_MISSING 유보를 보여 주기 위한 것이다.
    })
    store.write_json("goldset.json", GOLDSET)

    graph = store.approved()
    return {
        "log": log,
        "counts": graph.counts(),
        "documents": len(store.documents()),
    }


def _submitted_evidence(store: Store, today: date) -> list[dict[str, Any]]:
    """실제 제출된 증적과 SATISFIED_BY 엣지.

    근거 스팬은 증적 문서에서 잘라 붙인다 — "별첨05 3-2절이 이 통제의 증적이다"
    라는 주장이 문서의 어느 글자에서 나왔는지 남는다.
    """
    long_valid = (today + timedelta(days=300)).isoformat()
    expiring = (today + timedelta(days=10)).isoformat()
    started = (today - timedelta(days=60)).isoformat()

    submissions = [
        # (증적 uuid, 문서, 통제, 요구증적, 서비스, 만료일, 인용 시작 문구)
        ("evd-hi19-svc001", "evd-hi19-svc001", "HI-19", "req-hi19-doc", "svc-001",
         long_valid, "3-2. 단계별 이해관계자와 책임관계를"),
        ("evd-pf07-svc001", "evd-pf07-svc001", "PF-07", "req-pf07-report", "svc-001",
         long_valid, "2026년 2분기 정기 측정 결과"),
        # RM-03 은 요구 증적 2건 중 1건만 제출 — 부분충족 → 판단유보
        ("evd-rm03-svc001", "evd-rm03-svc001", "RM-03", "req-rm03-report", "svc-001",
         long_valid, "2026년 연차 위험 점검을 실시하고"),
        ("evd-mn05-svc002", "evd-mn05-svc002", "MN-05", "req-mn05-log", "svc-002",
         long_valid, "변경 요청·승인·반영 이력을"),
        # 만료 임박 — 룰은 충족으로 계산하지만 유보로 넘긴다
        ("evd-pf07-svc002", "evd-pf07-svc002", "PF-07", "req-pf07-report", "svc-002",
         expiring, "2026년 1분기 측정 결과"),
    ]

    ops: list[dict[str, Any]] = []
    documents = store.documents()
    for uuid, doc_id, code, required, svc, valid_to, needle in submissions:
        text = documents[doc_id]
        start = text.find(needle)
        end = text.find("\n", start)
        end = len(text) if end < 0 else end
        span = Span.of(doc_id, text, start, end, section="본문")
        ops.append(create_node("Evidence", {
            "uuid": uuid,
            "title": text.splitlines()[0],
            "evidence_kind": _kind_of(required),
            "required_yn": False,
            "doc_ref": doc_id,
            "sha256": span.sha256,
            "sign_yn": True,
            "signer": "부서장",
            "valid_from": started,
            "valid_to": valid_to,
            "status": "active",
        }, spans=[span.to_dict()], derivation="collected"))
        ops.append(create_edge(
            "SATISFIED_BY", node_id("Control", code=code),
            node_id("Evidence", uuid=uuid),
            {"service_uuid": svc, "for_required": node_id("Evidence", uuid=required)},
            spans=[span.to_dict()], derivation="collected",
        ))
    return ops


def _kind_of(required_uuid: str) -> str:
    for req in REQUIRED_EVIDENCE:
        if req["uuid"] == required_uuid:
            return str(req["evidence_kind"])
    return "기타"


#: 골드셋 — 사람이 붙인 정답. **그래프를 만들기 전에** 만들어야 하는 물건이다.
#: 공개 벤치마크는 이 도메인의 성능을 예측하지 못한다.
GOLDSET: list[dict[str, Any]] = [
    {"service": "svc-001", "control": "HI-19", "expected": "SATISFIED",
     "note": "책임관계 정의서 승인본 제출"},
    {"service": "svc-001", "control": "PF-07", "expected": "SATISFIED",
     "note": "AUC 0.82, 결과서 제출"},
    {"service": "svc-001", "control": "RM-03", "expected": "PARTIAL",
     "note": "점검 결과서만 있고 이력 없음 — 사람은 부분충족으로 봤다"},
    {"service": "svc-001", "control": "QA-11", "expected": "SATISFIED",
     "note": "정성 판단 — 심사자가 적정으로 봤다"},
    {"service": "svc-001", "control": "MN-05", "expected": "UNSATISFIED",
     "note": "변경 이력 대장 미제출"},
    {"service": "svc-001", "control": "TH-09", "expected": "UNSATISFIED",
     "note": "드리프트 임계치가 정해지지 않아 사람이 미충족으로 봤다"},
    {"service": "svc-002", "control": "PF-07", "expected": "SATISFIED",
     "note": "결과서 제출 (만료 임박)"},
    {"service": "svc-002", "control": "MN-05", "expected": "SATISFIED",
     "note": "변경 이력 대장 제출"},
]
