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
REG_NAME = "(샘플) 금융 AI 위험관리 지침"

SEED_AGENT = {"type": "Organization", "id": "system-seed"}

#: 데모용 샘플 조문. 실제 법령 원문이 아니다.
#: 어미를 일부러 섞어 두었다 — '하여야 한다'(필수) / '노력하여야 한다'·'바람직하다'
#: (권고) 가 각각 다른 강제력으로 잡히는지 이 문서 하나로 확인할 수 있다.
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

제6조(모형 변경관리) 금융회사는 운영 중인 모형의 변경 요청·승인·반영 이력을
기록하여야 한다.

제7조(드리프트 감시) 금융회사는 운영 중인 인공지능 서비스의 분포 변화를
감시하여야 하며, 개선 조치를 촉발하는 임계치를 정하여야 한다.

제8조(설명자료) 금융회사는 이용자에게 제공하는 인공지능 설명자료를 알기 쉽게
작성하는 것이 바람직하다.

제9조(외부 공급 모형) 금융회사가 외부에서 공급받은 모형을 사용하는 경우 공급자의
위험평가 자료를 받아 보관하여야 한다.

제10조(인적 감독) 금융회사는 고영향 인공지능 서비스의 자동화된 결정을 중지하거나
번복할 수 있는 책임자를 지정하여야 한다.

제11조(학습데이터 품질) 금융회사는 인공지능 서비스가 사용한 학습데이터의 출처와
품질 점검 내역을 기록하여야 한다.
"""
# ★ 제10·11조에는 대응 통제를 일부러 두지 않았다. 커버리지 갭 화면이 잡아내야
#   하는 것이 바로 이것 — "규제가 요구하는데 우리가 통제하지 않는 것" 이다.

#: 증적 원문 — 근거 스팬이 실재하는지 대조할 수 있어야 하므로 함께 적재한다.
EVIDENCE_DOCS: dict[str, str] = {
    "evd-acc-credit": (
        "책임관계 정의서 (여신심사 스코어링)\n"
        "3-2. 단계별 이해관계자와 책임관계를 아래 표와 같이 정의하고 "
        "AI거버넌스담당자의 승인을 받았다.\n"
        "승인일 2026-03-11 / 승인자 AI거버넌스담당자\n"
    ),
    "evd-perf-credit": (
        "성능 측정 결과서 (여신심사 스코어링)\n"
        "2026년 2분기 정기 측정 결과 AUC 0.82 로 사전에 정한 임계치를 충족하였다.\n"
    ),
    "evd-risk-credit": (
        "위험 점검 결과서 (여신심사 스코어링)\n"
        "2026년 연차 위험 점검을 실시하고 그 결과를 기록하였다.\n"
    ),
    "evd-chg-callcenter": (
        "모형 변경 이력 대장 (콜센터 요약 보조)\n"
        "변경 요청·승인·반영 이력을 대장에 기록하고 담당 부서장이 서명하였다.\n"
    ),
    "evd-perf-callcenter": (
        "성능 측정 결과서 (콜센터 요약 보조)\n"
        "2026년 1분기 측정 결과 요약 정확도 0.88 을 기록하였다.\n"
    ),
    "evd-acc-fraud": (
        "책임관계 정의서 (이상거래 탐지)\n"
        "2-4. 단계별 이해관계자와 책임관계를 정의하고 AI거버넌스담당자의 "
        "승인을 받았다.\n"
        "승인일 2026-01-20 / 승인자 AI거버넌스담당자\n"
    ),
    "evd-perf-fraud": (
        "성능 측정 결과서 (이상거래 탐지)\n"
        "2026년 2분기 측정 결과 탐지 AUC 0.71 로 임계치 0.75 에 미달하였다.\n"
    ),
    "evd-chg-fraud": (
        "모형 변경 이력 대장 (이상거래 탐지)\n"
        "변경 요청·승인·반영 이력을 대장에 기록하고 담당 부서장이 서명하였다.\n"
    ),
    "evd-vendor-fraud": (
        "외부 공급 모형 위험평가 자료 (이상거래 탐지)\n"
        "공급자가 2026년 배포본에 대한 모형 위험평가 자료를 제출하였고 "
        "리스크관리부가 검토하였다.\n"
    ),
    "evd-acc-marketing": (
        "책임관계 정의서 (마케팅 추천)\n"
        "3-1. 단계별 이해관계자와 책임관계를 정의하고 AI거버넌스담당자의 "
        "승인을 받았다.\n"
        "승인일 2026-05-02 / 승인자 AI거버넌스담당자\n"
    ),
}

# --- 통제 · 절차 · 요구 증적 ------------------------------------------------ #
CONTROLS: list[dict[str, Any]] = [
    {"code": "ACC-01", "title": "이해관계자 책임관계 명시 문서 작성",
     "title_en": "Document stakeholder accountability per AI service",
     "auto_level": "L1", "category": "책무", "owner": "AI거버넌스담당자"},
    {"code": "PRF-02", "title": "성능지표 정기 측정 및 임계치 관리",
     "title_en": "Measure performance indicators against a threshold",
     "auto_level": "L2", "category": "성능", "owner": "모델개발팀"},
    {"code": "RSK-03", "title": "연차 위험 점검 실시 및 결과 보존",
     "title_en": "Run an annual risk review and retain the result",
     "auto_level": "L1", "category": "위험점검", "owner": "리스크관리부"},
    {"code": "CHG-04", "title": "모형 변경 이력 관리",
     "title_en": "Keep a model change log",
     "auto_level": "L1", "category": "운영", "owner": "모델운영팀"},
    {"code": "DRF-05", "title": "운영 중 드리프트 감시",
     "title_en": "Monitor distribution drift in operation",
     "auto_level": "L2", "category": "성능", "owner": "모델운영팀"},
    {"code": "EXP-06", "title": "설명자료 적정성 판단",
     "title_en": "Assess whether explanatory material is adequate",
     "auto_level": "L3", "category": "정성", "owner": "AI거버넌스담당자"},
    {"code": "TPR-07", "title": "외부 공급 모형 위험평가 자료 보관",
     "title_en": "Retain third-party model risk assessment",
     "auto_level": "L1", "category": "외부위탁", "owner": "리스크관리부"},
    {"code": "DIS-08", "title": "성능지표 산출 근거 공개",
     "title_en": "Disclose how performance indicators are calculated",
     "auto_level": "L3", "category": "정성", "owner": "AI거버넌스담당자"},
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
     "title": "이해관계자 책임관계 정의서", "evidence_kind": "책임관계정의서",
     "function": "gov-doc-repo"},
    {"control": "PRF-02", "uuid": "req-performance-report",
     "title": "성능 측정 결과서", "evidence_kind": "성능측정결과서",
     "function": "mlops-metric-store"},
    {"control": "RSK-03", "uuid": "req-risk-review-report",
     "title": "위험 점검 결과서", "evidence_kind": "위험점검결과서",
     "function": "gov-doc-repo"},
    {"control": "RSK-03", "uuid": "req-risk-review-log",
     "title": "위험 점검 이력", "evidence_kind": "점검이력",
     "function": "itsm-change"},
    # ★ 증적 생산 기능이 없다 = 수기 의존 = 자동화 후보
    {"control": "CHG-04", "uuid": "req-change-log",
     "title": "모형 변경 이력 대장", "evidence_kind": "변경이력대장", "function": ""},
    {"control": "TPR-07", "uuid": "req-vendor-assessment",
     "title": "공급자 위험평가 자료", "evidence_kind": "공급자위험평가",
     "function": "gov-doc-repo"},
]

SYSTEM_FUNCTIONS: list[dict[str, Any]] = [
    {"key": "gov-doc-repo", "name": "거버넌스 문서 저장소", "system": "ITSM",
     "kind": "repository"},
    {"key": "mlops-metric-store", "name": "MLOps 지표 저장소", "system": "MLOps",
     "kind": "metric-store"},
    {"key": "itsm-change", "name": "변경관리 시스템", "system": "ITSM",
     "kind": "workflow"},
]

SERVICES: list[dict[str, Any]] = [
    {"uuid": "svc-credit-scoring", "name": "여신심사 스코어링",
     "name_en": "Credit Scoring", "dept": "여신기획부", "high_impact_yn": True},
    {"uuid": "svc-call-summary", "name": "콜센터 요약 보조",
     "name_en": "Call Center Summarizer", "dept": "고객지원부",
     "high_impact_yn": False},
    {"uuid": "svc-fraud-detect", "name": "이상거래 탐지",
     "name_en": "Fraud Detection", "dept": "리스크관리부", "high_impact_yn": True},
    {"uuid": "svc-marketing-rec", "name": "마케팅 추천",
     "name_en": "Marketing Recommender", "dept": "마케팅부", "high_impact_yn": False},
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
        name=REG_NAME, issuer="(샘플) 감독기관",
        effective_from="2026-06-01",
    )
    commit(intake.ops, {"type": "SoftwareAgent", "id": "collector-v1"},
           "규제 원문 수집")

    # L1 — 의무 제안 (LLM 없이 기준선 추출기)
    graph = store.approved()
    provisions = [n for n in graph.of_type("Provision")]
    proposal = propose_obligations(store, provisions, regulation_name=REG_NAME)
    commit(proposal.ops, {"type": "SoftwareAgent", "id": "slm-extract-v1"},
           "의무 추출 제안")
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
        ("책임관계를 문서로 명시", "ACC-01", "equivalent-to"),
        ("거버넌스 담당자의 승인", "ACC-01", "subset-of"),
        ("성능지표를 정기적으로 측정", "PRF-02", "subset-of"),
        ("임계치에 미달", "PRF-02", "subset-of"),
        ("점검을 실시", "RSK-03", "subset-of"),
        ("기록하고 보존", "RSK-03", "subset-of"),
        ("변경 요청·승인·반영 이력", "CHG-04", "equivalent-to"),
        ("분포 변화를 감시", "DRF-05", "equivalent-to"),
        ("알기 쉽게", "EXP-06", "intersects-with"),
        ("산출 근거를 이용자에게 공개", "DIS-08", "intersects-with"),
        ("공급자의 위험평가 자료", "TPR-07", "equivalent-to"),
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
    commit(ops, SEED_AGENT, "의무 → 통제 매핑")

    # 서비스 · 적용 · 제출 증적
    ops = []
    for svc in SERVICES:
        ops.append(create_node("Service", {**svc, "status": "active"}, derivation="human"))
    for code, svc_uuid in APPLIES:
        ops.append(create_edge(
            "APPLIES_TO", node_id("Control", code=code),
            node_id("Service", uuid=svc_uuid),
            {"reason": "적용 범위 판단(사람)"}, derivation="human",
        ))
    ops.extend(_submitted_evidence(store, today))
    commit(ops, SEED_AGENT, "서비스 등록 및 증적 제출")

    _open_changesets(store, commit_log=log)

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


def _open_changesets(store: Store, *, commit_log: list[str]) -> None:
    """결재를 기다리는 변경과 게이트에 막힌 변경을 하나씩 남긴다.

    시드가 전부 승인해 버리면 커밋 결재 화면에 아무것도 남지 않아 승인·반려
    버튼이 사라진다. 그 화면이 보여 줘야 하는 것은 '승인된 목록'이 아니라
    **결재를 기다리는 변경과, 게이트가 막아 세운 변경**이다.
    """
    # 1) 커버리지 갭에서 이어지는 제안 — 통제가 없던 제10조에 통제를 붙인다.
    #    갭 화면이 찾아낸 것을 사람이 메우는 흐름이 그대로 결재로 올라온다.
    graph = store.approved()
    target = next(
        (o for o in graph.of_type("Obligation")
         if "책임자를 지정" in " ".join(
             str(o["props"].get("text", "")).split())),
        None,
    )
    if target is not None:
        ops = [
            create_node("Control", {
                "code": "HUM-09",
                "title": "고영향 AI 결정 중지·번복 책임자 지정",
                "title_en": "Designate an override owner for high-impact AI",
                "auto_level": "L1", "category": "책무",
                "owner": "AI거버넌스담당자", "status": "active",
            }, derivation="human"),
            create_edge("IMPLEMENTED_BY", target["id"], node_id("Control", code="HUM-09"),
                        {"mapping_type": "equivalent-to"}, derivation="human"),
        ]
        pending = cs.stage(
            store, ops,
            proposer={"type": "Person", "id": "gov-officer"},
            source={"type": "review", "id": "제10조 커버리지 갭 해소"},
        )
        commit_log.append(f"{pending.changeset_id} [{pending.grade}] {pending.status} — "
                          "제10조 갭 해소용 신규 통제 (결재 대기)")

    # 2) 근거보다 센 주장 — 게이트 1 이 막는다 (blocked).
    #    제8조는 'should'(권고)인데 'mandatory'(필수)라고 주장하는 제안이다.
    text = store.document(REG_DOC_ID)
    quote = ("금융회사는 이용자에게 제공하는 인공지능 설명자료를 알기 쉽게\n"
             "작성하는 것이 바람직하다.")
    start = text.find(quote)
    if start >= 0:
        span = Span.of(REG_DOC_ID, text, start, start + len(quote), section="제8조")
        blocked = cs.stage(
            store,
            [create_node("Obligation", {
                "uuid": "obl-plain-language-overclaim",
                "title": "설명자료를 알기 쉽게 작성할 의무",
                "level": "mandatory",
            }, spans=[span.to_dict()])],
            proposer={"type": "SoftwareAgent", "id": "slm-extract-v1"},
            source={"type": "proposal", "id": "제8조 의무 제안"},
        )
        commit_log.append(f"{blocked.changeset_id} [{blocked.grade}] {blocked.status} — "
                          "권고를 필수로 과장 — 게이트가 막음")


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
         "svc-credit-scoring", long_valid, True, "3-2. 단계별 이해관계자와"),
        ("evd-perf-credit", "evd-perf-credit", "PRF-02", "req-performance-report",
         "svc-credit-scoring", long_valid, True, "2026년 2분기 정기 측정 결과"),
        # RSK-03 은 요구 증적 2건 중 1건만 제출 — 부분충족 → 판단유보
        ("evd-risk-credit", "evd-risk-credit", "RSK-03", "req-risk-review-report",
         "svc-credit-scoring", long_valid, True, "2026년 연차 위험 점검을"),
        ("evd-chg-callcenter", "evd-chg-callcenter", "CHG-04", "req-change-log",
         "svc-call-summary", long_valid, True, "변경 요청·승인·반영 이력을"),
        # 만료 임박 — 룰은 충족으로 계산하지만 유보로 넘긴다
        ("evd-perf-callcenter", "evd-perf-callcenter", "PRF-02", "req-performance-report",
         "svc-call-summary", expiring, True, "2026년 1분기 측정 결과"),
        ("evd-acc-fraud", "evd-acc-fraud", "ACC-01", "req-accountability-matrix",
         "svc-fraud-detect", long_valid, True, "2-4. 단계별 이해관계자와"),
        ("evd-perf-fraud", "evd-perf-fraud", "PRF-02", "req-performance-report",
         "svc-fraud-detect", long_valid, True, "2026년 2분기 측정 결과 탐지"),
        ("evd-chg-fraud", "evd-chg-fraud", "CHG-04", "req-change-log",
         "svc-fraud-detect", long_valid, True, "변경 요청·승인·반영 이력을"),
        ("evd-vendor-fraud", "evd-vendor-fraud", "TPR-07", "req-vendor-assessment",
         "svc-fraud-detect", long_valid, True, "공급자가 2026년 배포본에"),
        # 서명 없음 + 만료 — 룰이 증적으로 인정하지 않는다
        ("evd-acc-marketing", "evd-acc-marketing", "ACC-01", "req-accountability-matrix",
         "svc-marketing-rec", expired, False, "3-1. 단계별 이해관계자와"),
    ]

    ops: list[dict[str, Any]] = []
    documents = store.documents()
    for uuid, doc_id, code, required, svc, valid_to, signed, needle in submissions:
        text = documents[doc_id]
        start = text.find(needle)
        end = text.find("\n", start)
        end = len(text) if end < 0 else end
        span = Span.of(doc_id, text, start, end, section="본문")
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
            props["signer"] = "부서장"
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
    return "기타"


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
