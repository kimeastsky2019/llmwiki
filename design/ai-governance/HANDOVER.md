# AI 거버넌스 시스템 — 이어서 작업하기

미래에셋증권 AI 거버넌스 시스템 구축 사업(이니텍 수행, GnG 파트너) 대응 작업 묶음이다.
2026-09-05 시점의 상태와, VS Code 에서 이어받는 방법을 적었다.

---

## 1. 이 폴더에 무엇이 있나

| 파일 | 무엇인가 |
|---|---|
| `HANDOVER.md` | 이 문서 |
| `rfp-gap-check.html` | RFP 원문(Phase 1·2) 23개 절을 현재 구현과 대조한 갭 점검 |
| `mockup.html` | 역할별 화면 · IT 포털 3게이트 · 체크리스트 자동 식별 · sLLM 적용 지점 · 도우미 챗봇 목업 |

둘 다 단독 HTML 이다. 브라우저로 바로 열면 되고 빌드가 필요 없다.
VS Code 에서는 Live Preview 확장이나 `open design/ai-governance/mockup.html` 로 본다.

---

## 2. 사업 요건 요약 (RFP 기준)

발주처는 미래에셋증권, 수행사는 이니텍, GnG 는 파트너다.
**Phase 1 = 프로세스(연내)**, **Phase 2 = 평가 지표·자동화**로 갈린다.

회의 녹취로 잡았던 판단 중 네 가지가 RFP 원문과 달랐다. 이어받을 때 이것부터 본다.

1. **IT 포털 접점은 2개가 아니라 3개다.**
   ① SR 접수 식별 → 프로젝트 생성 ② IT 접수 전 위험관리계획 승인(미승인 시 접수 불가)
   ③ PMO 종료 전 위험경감 검증 승인(미승인 시 종료 불가)
2. **점수제를 버리지 않는다.** RFP 가.C 가 "항목별 위험점수 관리"와 "잔여위험비율 관리"를 명시한다.
   지금 32항목 배점과 완화 가중치가 이 문구에 맞는다.
3. **RFP 가 말하는 자동화는 LLM 실측이 아니다.** 체크리스트 → 위험항목 자동 식별 →
   경감방안 사전 맵핑 자동 도출 → 경감비율 100% 사전 적용, 전부 수기 수정 가능.
4. **전자결재는 연동 확정**이고, 통합인증·보안 SW 는 발주처 운영 제품으로 구성해야 한다.

집계: 23건 중 있음 1 · 부분 10 · 없음 12. **연내 과제인 프로세스 통제가 가장 비어 있다.**

---

## 3. 코드에 들어간 것 (이번 작업분)

기획서 §06 의 1~3단계, 즉 **소스 분석과 규제 검증을 잇는 다리**까지 구현했다.

### 백엔드

| 파일 | 한 일 |
|---|---|
| `llmwiki/compliance/ontology.py` | `REALIZED_BY`(Service→SystemFunction) 엣지 추가. 온톨로지 1.0.0 → **1.1.0** |
| `llmwiki/compliance/propose.py` | `propose_service()` — 프로그램 묶음 → Service + SystemFunction + REALIZED_BY |
| `llmwiki/compliance/analysis.py` | 서비스 축 집계 — `services()` `service_detail()` `service_stage()` |
| `llmwiki/compliance/codehints.py` **신규** | 정적 분석 사실 → 프로파일·위험항목 **후보** 제안 |
| `llmwiki/compliance/data/code_hints.yaml` **신규** | 제안 패턴 단일 원본 (명명규칙은 현장마다 달라 데이터로 뺐다) |
| `llmwiki/server/compliance.py` | `/api/reg/programs · services · service/{uuid} · services/propose · risk/suggest` |
| `tests/test_compliance_api.py` | 신규 테스트 6건 |

지켜야 하는 선이 두 개 있다. 코드가 아니라 테스트가 지킨다.

* **승인 그래프에 직접 쓰는 엔드포인트를 만들지 않는다.** 서비스 정의도 ChangeSet 으로
  결재 큐에 올라간다. `test_there_is_no_endpoint_that_writes_the_graph_directly` 가 목록을 고정한다.
* **`Service` 와 `REALIZED_BY` 는 sLM 이 제안할 수 없다**(`llm_proposable=False`).
  서비스 경계는 업무 판단이라서다. `test_an_slm_may_not_propose_a_service` 가 막는다.

### 프론트

`web/src/Services.tsx` **신규**(서비스 목록·정의·대시보드·사이드바 서비스 트리),
`App.tsx`(`/` → 규제 서비스 목록, 프로그램 목록은 `/programs`, `/svc/<id>` 라우트),
`Compliance.tsx`(서비스 탭 추가, 화면 안 탭 줄 제거 — 사이드바와 중복이라),
`RiskWizard.tsx`(STEP2·STEP3 에 코드 근거 제안 칩), `api.ts` `i18n.ts` `solutions.ts` `styles.css`.

솔루션 탭은 **소스 분석 / 규제 준수 평가** 둘이다. 리포트 지식화는 `solutions.ts` 의
`hidden: true` 한 줄로 메뉴에서만 감췄다 — `/kb` `/wiki` `/admin` 로 직접 들어가면 그대로 동작한다.

### 배포

`deploy/gpu-server/` — 210.206.73.80(Ubuntu 24.04 · A30 24GB) 용 키트.
`bootstrap.sh`(서버 1회) · `push.sh`(맥에서 빌드·전송) · `config.gpu.yaml` ·
`llmwiki.service` · `nginx-llmwiki.conf` · `README.md`.

이전 서버와 다른 점 하나. **기본 공급자가 사내 sLLM(Ollama)** 이다. GPU 를 혼자 쓰므로
소스와 규제 문서가 조직 밖으로 나가지 않는 구성이 기본값이 된다.

---

## 4. 실행 방법

### 백엔드 · 테스트

```bash
cd ~/Documents/Sloution/LLMWiki
uv run pytest -q                      # 또는 .venv/bin/python -m pytest -q
uv run uvicorn llmwiki.server.app:app --port 8722 --reload
```

`.venv` 는 /opt/anaconda3 를 가리키고 있다. 깨져 있으면 새로 만든다.

```bash
uv venv --python 3.12 && uv pip install -e . && uv pip install pytest
```

**실패 2건은 원래 있던 것이다** — `test_i18n_and_source.py::test_error_messages_follow_lang_param`,
`test_kb.py::test_many_distinct_terms_beat_one_repeated_term`. 내 변경과 무관하다.
그 밖에 514건이 통과해야 정상이다.

### 프론트

```bash
cd web && npm install && npm run dev      # 개발 서버
npm run build                             # tsc -b + vite build
```

`vite build` 는 맥에서만 된다. `node_modules` 의 rollup 네이티브 바이너리가 darwin 용이다.

### 서버 배포

```bash
read -rs XAI_API_KEY && export XAI_API_KEY
./deploy/gpu-server/push.sh --bootstrap   # 처음 한 번
./deploy/gpu-server/push.sh               # 이후 재배포
```

---

## 5. 다음 할 일

앞의 것이 없으면 뒤의 것이 의미가 없는 순서다.

1. **산출물 15종 서식 목록** — 문서별 항목과 자동 채움 가능 범위를 표로.
   착수 후 첫 병목이 여기다. 서식이 늦으면 개발이 통째로 밀린다.
2. **가견적** — Phase 1 / Phase 2 분리. 추가 SW 는 제안사 부담(RFP 아.C)이므로 기본 범위에서 뺀다.
3. **프로세스 통제 구현** — 프로젝트 라이프사이클, 결재(계획·관리 2회), 조직·롤·위원회, IT 포털 3게이트.
   현재 있는 ChangeSet 결재는 *기준 변경* 결재라 그대로 쓸 수 없다. 등급→결재자 매핑 구조만 재사용한다.
4. **Phase 2 자동화 가능 항목표** — AI-RMF 항목마다 자동/반자동/수기를 갈라 제안서에 넣는다.

### 고객에게 받아야 하는 것

* 역할별 실제 사용자 목록(부서·인원·접근 범위)
* 연동 대상: 통합인증·보안 제품, 전자결재 API, 알림 API, 인사 테이블
* 산출물 15종 서식

---

## 6. 주의

* **`compliance/` `knowledge/` `wiki/` 는 append-only 감사 추적이다.** 재생성 가능한 산출물이 아니다.
  지우면 과거 판정의 근거가 사라진다. `.gitignore` 에 있으니 별도로 백업한다.
* **iCloud 가 소스를 비운다.** 이 저장소는 iCloud Drive 안에 있어 파일이 스텁이 되는 일이 반복됐다.
  읽히지 않는 파일이 생기면 `git show HEAD:<경로> > <경로>` 로 되살리거나 Finder 에서 다운로드한다.
  아직 비어 있는 파일: `design/*.md` 3개, `llmwiki/ediag/README.md`, `llmwiki/kb/README.md`.
* **xAI 키는 저장소에 넣지 않는다.** `/etc/llmwiki/llmwiki.env` 에만 둔다.
  2026-09-05 대화에 키가 평문으로 노출됐으므로 **폐기하고 재발급**할 것.
* `llmwiki/server/ediag.py.bak-20260827124512` 는 백업 파일이라 커밋하지 않았다. 필요 없으면 지운다.
