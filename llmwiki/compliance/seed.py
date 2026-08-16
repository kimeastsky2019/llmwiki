"""데모 데이터 — 설정 없이 전체 흐름을 한 번 돌려 볼 수 있게 한다.

`sample/` 이 소스 분석 데모인 것과 같은 역할이다. 여기 들어 있는 규제 원문은
**실제 법령이 아니라 데모용으로 작성한 샘플**이다. 조문 형식과 어미(shall /
should / may)만 실제와 같게 맞춰, 조문 분할·근거 대조·인용 강도 검증이
실제로 동작하는지 볼 수 있게 했다.

화면·데이터를 영어로 통일한 이유: 판정 라벨과 사유가 룰 엔진에서 영어로
나오는데 데이터만 한국어면 한 행 안에서 두 언어가 섞여 오히려 읽기 어렵다.

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

REG_DOC_ID = "ai-risk-guideline-2026"
REG_UUID = "reg-ai-risk-2026"
REG_NAME = "AI Risk Management Guideline for Financial Institutions (Sample)"

SEED_AGENT = {"type": "Organization", "id": "system-seed"}

#: 데모용 샘플 조문. 실제 법령 원문이 아니다.
#: 어미를 일부러 섞어 두었다 — shall(필수) / should(권고) / may(재량) 가
#: 각각 다른 강제력으로 잡히는지 이 문서 하나로 확인할 수 있다.
REGULATION_TEXT = """AI Risk Management Guideline for Financial Institutions (Sample)

Article 1 (Purpose) This guideline sets out the risk management requirements a
financial institution shall observe when it introduces and operates an artificial
intelligence service.

Article 2 (Definition) In this guideline, "high-impact AI" means an artificial
intelligence service that may materially affect the rights or obligations of an
individual.

Article 3 (Accountability) A financial institution shall document, for each AI
service, the stakeholders and their responsibilities across the planning,
development, operation and review stages. The document shall be approved by the
AI governance officer.

Article 4 (Performance management) A financial institution shall measure the
performance indicators of an AI service on a regular basis. Where an indicator
falls below a predefined threshold, the institution shall take corrective action.
A financial institution should disclose to users the basis on which performance
indicators are calculated.

Article 5 (Risk review) A financial institution shall carry out a risk review of
a high-impact AI service at least once a year. The result of the review shall be
recorded and retained.

Article 6 (Model change control) A financial institution shall keep a record of
every change to a model in operation, including the request, the approval and the
deployment.

Article 7 (Drift monitoring) A financial institution shall monitor an AI service
in operation for distribution drift and shall define the threshold at which
corrective action is triggered.

Article 8 (Explanatory material) Explanatory material provided to users should be
written in plain language. A financial institution may publish the material on its
website.

Article 9 (Third-party models) Where a financial institution uses a model supplied
by a third party, it shall obtain and retain evidence of the supplier's risk
assessment.

Article 10 (Human oversight) A financial institution shall designate a person who
can suspend or override an automated decision of a high-impact AI service.

Article 11 (Training data quality) A financial institution shall record the source
of the training data used by an AI service and the quality checks applied to it.
"""
# ★ 제10·11조에는 대응 통제를 일부러 두지 않았다. 커버리지 갭 화면이 잡아내야
#   하는 것이 바로 이것 — "규제가 요구하는데 우리가 통제하지 않는 것" 이다.

#: 증적 원문 — 근거 스팬이 실재하는지 대조할 수 있어야 하므로 함께 적재한다.
EVIDENCE_DOCS: dict[str, str] = {
    "evd-acc-credit": (
        "Accountability Matrix — Credit Scoring\n"
        "3-2. Stakeholders and their responsibilities for each stage are defined in "
        "the table below and were approved by the AI governance officer.\n"
        "Approved 2026-03-11 / Approver: AI governance officer\n"
    ),
    "evd-perf-credit": (
        "Performance Measurement Report — Credit Scoring\n"
        "The regular measurement for Q2 2026 recorded an AUC of 0.82, which meets the "
        "predefined threshold.\n"
    ),
    "evd-risk-credit": (
        "Annual Risk Review Report — Credit Scoring\n"
        "The 2026 annual risk review was carried out and its result was recorded.\n"
    ),
    "evd-chg-callcenter": (
        "Model Change Log — Call Center Summarizer\n"
        "Change requests, approvals and deployments are recorded in the log and signed "
        "by the responsible team lead.\n"
    ),
    "evd-perf-callcenter": (
        "Performance Measurement Report — Call Center Summarizer\n"
        "The Q1 2026 measurement recorded a summary accuracy of 0.88.\n"
    ),
    "evd-acc-fraud": (
        "Accountability Matrix — Fraud Detection\n"
        "2-4. Stakeholders and their responsibilities for each stage are defined and "
        "were approved by the AI governance officer.\n"
        "Approved 2026-01-20 / Approver: AI governance officer\n"
    ),
    "evd-perf-fraud": (
        "Performance Measurement Report — Fraud Detection\n"
        "The Q2 2026 measurement recorded a detection AUC of 0.71 against a threshold "
        "of 0.75.\n"
    ),
    "evd-chg-fraud": (
        "Model Change Log — Fraud Detection\n"
        "Change requests, approvals and deployments are recorded in the log and signed "
        "by the responsible team lead.\n"
    ),
    "evd-vendor-fraud": (
        "Third-party Risk Assessment — Fraud Detection\n"
        "The supplier provided its model risk assessment for the 2026 release and it "
        "was reviewed by the risk management department.\n"
    ),
    "evd-acc-marketing": (
        "Accountability Matrix — Marketing Recommender\n"
        "3-1. Stakeholders and their responsibilities for each stage are defined and "
        "were approved by the AI governance officer.\n"
        "Approved 2026-05-02 / Approver: AI governance officer\n"
    ),
}

# --- 통제 · 절차 · 요구 증적 ------------------------------------------------ #
CONTROLS: list[dict[str, Any]] = [
    {"code": "ACC-01", "title": "Document stakeholder accountability per AI service",
     "auto_level": "L1", "category": "Accountability",
     "owner": "AI governance officer"},
    {"code": "PRF-02", "title": "Measure performance indicators against a threshold",
     "auto_level": "L2", "category": "Performance", "owner": "Model development team"},
    {"code": "RSK-03", "title": "Run an annual risk review and retain the result",
     "auto_level": "L1", "category": "Risk review", "owner": "Risk management"},
    {"code": "CHG-04", "title": "Keep a model change log",
     "auto_level": "L1", "category": "Operations", "owner": "Model operations team"},
    {"code": "DRF-05", "title": "Monitor distribution drift in operation",
     "auto_level": "L2", "category": "Performance", "owner": "Model operations team"},
    {"code": "EXP-06", "title": "Assess whether explanatory material is adequate",
     "auto_level": "L3", "category": "Qualitative", "owner": "AI governance officer"},
    {"code": "TPR-07", "title": "Retain third-party model risk assessment",
     "auto_level": "L1", "category": "Third party", "owner": "Risk management"},
    {"code": "DIS-08", "title": "Disclose how performance indicators are calculated",
     "auto_level": "L3", "category": "Qualitative", "owner": "AI governance officer"},
]

PROCEDURES: list[dict[str, Any]] = [
    {"control_code": "ACC-01", "seq": "1", "kind": "evidence"},
    {"control_code": "PRF-02", "seq": "1", "kind": "evidence"},
    {"control_code": "PRF-02", "seq": "2", "kind": "metric",
     "metric": "model_auc", "operator": ">=", "threshold": 0.75, "unit": ""},
    {"control_code": "RSK-03", "seq": "1", "kind": "evidence"},
    {"control_code": "CHG-04", "seq": "1", "kind": "evidence"},
    # ★ 임계치 미정 — 산출물의 위험 항목 중 임계치를 가진 것은 3분의 1뿐이었다.
    #   이런 항목은 자동 판정하지 않고 판단 유보로 넘긴다.
    {"control_code": "DRF-05", "seq": "1", "kind": "metric", "metric": "drift_psi"},
    {"control_code": "EXP-06", "seq": "1", "kind": "qualitative"},
    {"control_code": "TPR-07", "seq": "1", "kind": "evidence"},
    {"control_code": "DIS-08", "seq": "1", "kind": "qualitative"},
]

REQUIRED_EVIDENCE: list[dict[str, Any]] = [
    {"control": "ACC-01", "uuid": "req-accountability-matrix",
     "title": "Accountability matrix", "evidence_kind": "accountability-matrix",
     "function": "gov-doc-repo"},
    {"control": "PRF-02", "uuid": "req-performance-report",
     "title": "Performance measurement report", "evidence_kind": "performance-report",
     "function": "mlops-metric-store"},
    {"control": "RSK-03", "uuid": "req-risk-review-report",
     "title": "Risk review report", "evidence_kind": "risk-review-report",
     "function": "gov-doc-repo"},
    {"control": "RSK-03", "uuid": "req-risk-review-log",
     "title": "Risk review trail", "evidence_kind": "review-trail",
     "function": "itsm-change"},
    # ★ 증적 생산 기능이 없다 = 수기 의존 = 자동화 후보
    {"control": "CHG-04", "uuid": "req-change-log",
     "title": "Model change log", "evidence_kind": "change-log", "function": ""},
    {"control": "TPR-07", "uuid": "req-vendor-assessment",
     "title": "Supplier risk assessment", "evidence_kind": "vendor-assessment",
     "function": "gov-doc-repo"},
]

SYSTEM_FUNCTIONS: list[dict[str, Any]] = [
    {"key": "gov-doc-repo", "name": "Governance document repository", "system": "ITSM",
     "kind": "repository"},
    {"key": "mlops-metric-store", "name": "MLOps metric store", "system": "MLOps",
     "kind": "metric-store"},
    {"key": "itsm-change", "name": "Change management system", "system": "ITSM",
     "kind": "workflow"},
]

SERVICES: list[dict[str, Any]] = [
    {"uuid": "svc-credit-scoring", "name": "Credit Scoring", "dept": "Credit Planning",
     "high_impact_yn": True},
    {"uuid": "svc-call-summary", "name": "Call Center Summarizer",
     "dept": "Customer Support", "high_impact_yn": False},
    {"uuid": "svc-fraud-detect", "name": "Fraud Detection", "dept": "Risk Management",
     "high_impact_yn": True},
    {"uuid": "svc-marketing-rec", "name": "Marketing Recommender", "dept": "Marketing",
     "high_impact_yn": False},
]

#: 어떤 통제가 어떤 서비스에 적용되는가. 판정 대상은 이 목록이 정한다.
#: 고영향 서비스에만 붙는 통제(RSK-03)를 섞어, 적용 범위가 서비스마다
#: 다르다는 점이 화면에 드러나게 했다.
APPLIES: list[tuple[str, str]] = [
    # Credit Scoring — 고영향, 전 통제 적용
    ("ACC-01", "svc-credit-scoring"), ("PRF-02", "svc-credit-scoring"),
    ("RSK-03", "svc-credit-scoring"), ("CHG-04", "svc-credit-scoring"),
    ("DRF-05", "svc-credit-scoring"), ("EXP-06", "svc-credit-scoring"),
    ("DIS-08", "svc-credit-scoring"),
    # Call Center Summarizer — 저영향, 연차 위험 점검 제외
    ("ACC-01", "svc-call-summary"), ("PRF-02", "svc-call-summary"),
    ("CHG-04", "svc-call-summary"), ("EXP-06", "svc-call-summary"),
    # Fraud Detection — 고영향 + 외부 공급 모형
    ("ACC-01", "svc-fraud-detect"), ("PRF-02", "svc-fraud-detect"),
    ("RSK-03", "svc-fraud-detect"), ("CHG-04", "svc-fraud-detect"),
    ("DRF-05", "svc-fraud-detect"), ("TPR-07", "svc-fraud-detect"),
    # Marketing Recommender — 저영향
    ("ACC-01", "svc-marketing-rec"), ("CHG-04", "svc-marketing-rec"),
    ("DIS-08", "svc-marketing-rec"),
]

AGENTS: list[dict[str, Any]] = [
    {"agent_id": "rule-engine", "name": "Verdict rule engine", "kind": "SoftwareAgent",
     "dept": "Platform"},
    {"agent_id": "gov-officer", "name": "AI governance officer", "kind": "Person",
     "dept": "AI Governance"},
    {"agent_id": "ai-governance", "name": "AI governance committee",
     "kind": "Organization"},
    {"agent_id": "system-seed", "name": "Initial load", "kind": "Organization"},
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
        name=REG_NAME, issuer="Financial Supervisory Authority (Sample)",
        effective_from="2026-06-01",
    )
    commit(intake.ops, {"type": "SoftwareAgent", "id": "collector-v1"},
           "Regulation intake")

    # L1 — 의무 제안 (LLM 없이 기준선 추출기)
    graph = store.approved()
    provisions = [n for n in graph.of_type("Provision")]
    proposal = propose_obligations(store, provisions, regulation_name=REG_NAME)
    commit(proposal.ops, {"type": "SoftwareAgent", "id": "slm-extract-v1"},
           "Obligation extraction")
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
        "version": RULESET_VERSION, "name": "Baseline verdict ruleset",
        "standard_version": "2026.08", "status": "active",
    }, derivation="human"))
    commit(ops, SEED_AGENT, "Controls, procedures, required evidence and ruleset")

    # 의무 → 통제 매핑 (사람이 정한다)
    graph = store.approved()
    # 근거 문장(text)으로 매칭한다. 제목은 잘려 있을 수 있어 기준으로 삼지 않는다.
    mapping: list[tuple[str, str, str]] = [
        ("document, for each AI", "ACC-01", "equivalent-to"),
        ("approved by the", "ACC-01", "subset-of"),
        ("measure the performance indicators", "PRF-02", "subset-of"),
        ("falls below a predefined threshold", "PRF-02", "subset-of"),
        ("carry out a risk review", "RSK-03", "subset-of"),
        ("recorded and retained", "RSK-03", "subset-of"),
        ("record of\nevery change", "CHG-04", "equivalent-to"),
        ("distribution drift", "DRF-05", "equivalent-to"),
        ("plain language", "EXP-06", "intersects-with"),
        ("disclose to users", "DIS-08", "intersects-with"),
        ("supplier's risk", "TPR-07", "equivalent-to"),
    ]
    ops = []
    linked: set[str] = set()
    for keyword, code, mapping_type in mapping:
        needle = " ".join(keyword.split())
        for obl in graph.of_type("Obligation"):
            body = " ".join(str(obl["props"].get("text", "")).split())
            if needle not in body:
                continue
            key = f"{obl['id']}->{code}"
            if key in linked:
                continue
            linked.add(key)
            ops.append(create_edge(
                "IMPLEMENTED_BY", obl["id"], node_id("Control", code=code),
                {"mapping_type": mapping_type}, derivation="human",
            ))
    commit(ops, SEED_AGENT, "Obligation to control mapping")

    # 서비스 · 적용 · 제출 증적
    ops = []
    for svc in SERVICES:
        ops.append(create_node("Service", {**svc, "status": "active"}, derivation="human"))
    for code, svc_uuid in APPLIES:
        ops.append(create_edge(
            "APPLIES_TO", node_id("Control", code=code),
            node_id("Service", uuid=svc_uuid),
            {"reason": "Scoping decision (human)"}, derivation="human",
        ))
    ops.extend(_submitted_evidence(store, today))
    commit(ops, SEED_AGENT, "Services and submitted evidence")

    # 지표 측정값 · 골드셋
    store.write_json("metrics.json", {
        "svc-credit-scoring": {"model_auc": 0.82, "drift_psi": 0.12},
        # AUC 가 임계치 미달 — UNSATISFIED 를 보여 준다.
        "svc-fraud-detect": {"model_auc": 0.71},
        # 나머지 서비스는 측정값이 없다 — METRIC_MISSING 유보를 보여 주기 위한 것이다.
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

    근거 스팬은 증적 문서에서 잘라 붙인다 — "이 문서의 3-2절이 이 통제의
    증적이다" 라는 주장이 문서의 어느 글자에서 나왔는지 남는다.
    """
    long_valid = (today + timedelta(days=300)).isoformat()
    expiring = (today + timedelta(days=10)).isoformat()
    expired = (today - timedelta(days=5)).isoformat()
    started = (today - timedelta(days=60)).isoformat()

    submissions = [
        # (증적 uuid, 문서, 통제, 요구증적, 서비스, 만료일, 서명, 인용 시작 문구)
        ("evd-acc-credit", "evd-acc-credit", "ACC-01", "req-accountability-matrix",
         "svc-credit-scoring", long_valid, True, "3-2. Stakeholders and their"),
        ("evd-perf-credit", "evd-perf-credit", "PRF-02", "req-performance-report",
         "svc-credit-scoring", long_valid, True, "The regular measurement for Q2 2026"),
        # RSK-03 은 요구 증적 2건 중 1건만 제출 — 부분충족 → 판단유보
        ("evd-risk-credit", "evd-risk-credit", "RSK-03", "req-risk-review-report",
         "svc-credit-scoring", long_valid, True, "The 2026 annual risk review"),
        ("evd-chg-callcenter", "evd-chg-callcenter", "CHG-04", "req-change-log",
         "svc-call-summary", long_valid, True, "Change requests, approvals and"),
        # 만료 임박 — 룰은 충족으로 계산하지만 유보로 넘긴다
        ("evd-perf-callcenter", "evd-perf-callcenter", "PRF-02", "req-performance-report",
         "svc-call-summary", expiring, True, "The Q1 2026 measurement recorded"),
        ("evd-acc-fraud", "evd-acc-fraud", "ACC-01", "req-accountability-matrix",
         "svc-fraud-detect", long_valid, True, "2-4. Stakeholders and their"),
        ("evd-perf-fraud", "evd-perf-fraud", "PRF-02", "req-performance-report",
         "svc-fraud-detect", long_valid, True, "The Q2 2026 measurement recorded"),
        ("evd-chg-fraud", "evd-chg-fraud", "CHG-04", "req-change-log",
         "svc-fraud-detect", long_valid, True, "Change requests, approvals and"),
        ("evd-vendor-fraud", "evd-vendor-fraud", "TPR-07", "req-vendor-assessment",
         "svc-fraud-detect", long_valid, True, "The supplier provided its model"),
        # 서명 없음 — 룰이 증적으로 인정하지 않는다
        ("evd-acc-marketing", "evd-acc-marketing", "ACC-01", "req-accountability-matrix",
         "svc-marketing-rec", expired, False, "3-1. Stakeholders and their"),
    ]

    ops: list[dict[str, Any]] = []
    documents = store.documents()
    for uuid, doc_id, code, required, svc, valid_to, signed, needle in submissions:
        text = documents[doc_id]
        start = text.find(needle)
        end = text.find("\n", start)
        end = len(text) if end < 0 else end
        span = Span.of(doc_id, text, start, end, section="body")
        props: dict[str, Any] = {
            "uuid": uuid,
            "title": text.splitlines()[0],
            "evidence_kind": _kind_of(required),
            "required_yn": False,
            "doc_ref": doc_id,
            "sha256": span.sha256,
            "sign_yn": signed,
            "valid_from": started,
            "valid_to": valid_to,
            "status": "active",
        }
        if signed:
            props["signer"] = "Team lead"
        ops.append(create_node("Evidence", props, spans=[span.to_dict()],
                               derivation="collected"))
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
    return "other"


#: 골드셋 — 사람이 붙인 정답. **그래프를 만들기 전에** 만들어야 하는 물건이다.
#: 공개 벤치마크는 이 도메인의 성능을 예측하지 못한다.
GOLDSET: list[dict[str, Any]] = [
    {"service": "svc-credit-scoring", "control": "ACC-01", "expected": "SATISFIED",
     "note": "Approved accountability matrix submitted"},
    {"service": "svc-credit-scoring", "control": "PRF-02", "expected": "SATISFIED",
     "note": "AUC 0.82 with report submitted"},
    {"service": "svc-credit-scoring", "control": "RSK-03", "expected": "PARTIAL",
     "note": "Review report present but no review trail — reviewer called it partial"},
    {"service": "svc-credit-scoring", "control": "CHG-04", "expected": "UNSATISFIED",
     "note": "No change log submitted"},
    {"service": "svc-credit-scoring", "control": "DRF-05", "expected": "UNSATISFIED",
     "note": "No drift threshold defined — reviewer called it not satisfied"},
    {"service": "svc-credit-scoring", "control": "EXP-06", "expected": "SATISFIED",
     "note": "Qualitative — reviewer judged the material adequate"},
    {"service": "svc-credit-scoring", "control": "DIS-08", "expected": "UNSATISFIED",
     "note": "Calculation basis is not published"},
    {"service": "svc-call-summary", "control": "ACC-01", "expected": "UNSATISFIED",
     "note": "No accountability matrix submitted"},
    {"service": "svc-call-summary", "control": "PRF-02", "expected": "SATISFIED",
     "note": "Report submitted (expiring soon)"},
    {"service": "svc-call-summary", "control": "CHG-04", "expected": "SATISFIED",
     "note": "Change log submitted"},
    {"service": "svc-call-summary", "control": "EXP-06", "expected": "SATISFIED",
     "note": "Qualitative — reviewer judged the material adequate"},
    {"service": "svc-fraud-detect", "control": "ACC-01", "expected": "SATISFIED",
     "note": "Approved accountability matrix submitted"},
    {"service": "svc-fraud-detect", "control": "PRF-02", "expected": "PARTIAL",
     "note": "Report submitted but AUC 0.71 is below the 0.75 threshold"},
    {"service": "svc-fraud-detect", "control": "RSK-03", "expected": "UNSATISFIED",
     "note": "No risk review evidence submitted"},
    {"service": "svc-fraud-detect", "control": "CHG-04", "expected": "SATISFIED",
     "note": "Change log submitted"},
    {"service": "svc-fraud-detect", "control": "DRF-05", "expected": "UNSATISFIED",
     "note": "No drift threshold defined"},
    {"service": "svc-fraud-detect", "control": "TPR-07", "expected": "SATISFIED",
     "note": "Supplier risk assessment retained"},
    {"service": "svc-marketing-rec", "control": "ACC-01", "expected": "UNSATISFIED",
     "note": "Matrix submitted but unsigned and expired — does not count"},
    {"service": "svc-marketing-rec", "control": "CHG-04", "expected": "UNSATISFIED",
     "note": "No change log submitted"},
    {"service": "svc-marketing-rec", "control": "DIS-08", "expected": "UNSATISFIED",
     "note": "Calculation basis is not published"},
]
