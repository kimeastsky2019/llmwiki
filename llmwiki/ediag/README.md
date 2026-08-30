# 에너지 진단 위키 (ediag)

> 진단 보고서(PDF)를 **데이터 컨트랙트가 걸린 마크다운 위키**로 세우고,
> **수치는 코드가 계산·검산**하며, **확정은 사람이 서명**한다.

LLMWiki 의 네 번째 그래프다.

| 모듈 | 대상 | 산출물 | 판정 주체 |
|---|---|---|---|
| `llmwiki/` | 레거시 소스 코드 | 프로그램 명세서 | 파서 |
| `llmwiki/compliance/` | 조직의 규정·통제 | 규제 지식그래프 | 룰 + 사람 확정 |
| `llmwiki/kb/` | 업무 문서(PDF) | 4채널 청크 + 문서 온톨로지 | 룰 |
| **`llmwiki/ediag/`** | **진단 보고서** | **마크다운 위키 + 검산 결과** | **코드 + 사람 서명** |

`kb` 가 PDF 를 채널로 갈라 담는 곳이라면, 여기는 그 결과가 **사람이 읽고 고칠 수 있는
페이지**로 서는 곳이다. 이 모듈도 LLM 을 부르지 않는다.

---

## 왜 RAG 가 아니라 위키인가

벡터 RAG 는 검색해서 답하는 데서 끝난다. 진단 보고서는 그걸로 부족하다.

* 법규·단가·배출계수가 **주기적으로 개정**된다 → 유효기간과 재생성이 필요하다
* 같은 사업장을 **수년 주기로 재진단**한다 → 문서 간 시계열 정합성이 필요하다
* 숫자가 틀리면 **바로 사업 리스크**가 된다 → 출처 추적과 검산이 필수다

그래서 검색 계층이 아니라 소스 계층부터 세운다. 위키가 원본이고, 인덱스·그래프·검색은
전부 위키에서 **재생성**한다.

---

## 설계 원칙 (Non-negotiables)

| # | 원칙 | 집행 지점 |
|---|---|---|
| P1 | Single Source of Truth 는 위키다 | `store.py` — index.md·log.md·그래프는 재생성물 |
| P2 | **숫자는 LLM 이 생성하지 않는다** | `calc.py` + `numeric_verified` 게이트 |
| P3 | 모든 페이지는 데이터 컨트랙트를 갖는다 | `contract.py` — 없으면 파이프라인 진입 금지 |
| P4 | Lint 는 주기 작업이다 | `lint.py` — 생성 직후 1회 + 주 1회 |
| P5 | **ACL 이 모델 라우팅을 결정한다** | `route.py` + `lint.acl.inheritance` (배포 차단) |

---

## 파이프라인

```
PDF ─▶ kb 파싱(4채널) ─▶ 적재 게이트(개인정보/AI기본법)
                              │  막히면 ─▶ 페이지를 만들지 않는다
                              ▼
                        규칙 추출 (extract.py)
                        표 · 본문 계산식 · 서술
                              │
                              ▼
                        수치 검산 (calc.py)   ← 원문 값 vs 재계산
                              │
                              ▼
                     페이지 생성 (build.py)  전부 draft 로 태어난다
                              │
                              ▼
                     저장 (store.py) ─▶ lint.py ─▶ 검증 큐 (review.py)
                              │                         │
                              ▼                         ▼
                     검색 (retrieval.py)          사람의 서명 → reviewed
```

| 파일 | 역할 |
|---|---|
| `contract.py` | front-matter 규격 · 닫힌 집합 · 검증 |
| `data/units.yaml` | **계수·단가 SSOT** (유효기간 포함) |
| `units.py` | 단위 테이블 로더 · 만료 임박 탐지 |
| `calc.py` | toe 환산 · 배출량 · 절감 · 회수기간 + **검산** |
| `extract.py` | 표·계산식·서술에서 사실 추출 (규칙만) |
| `terms.py` | 한글 명칭 → ASCII ID 사전 · ECM 카드 목록 |
| `build.py` | 추출 결과 → 위키 페이지 |
| `page.py` | front-matter + 마크다운 직렬화 |
| `store.py` | 파일 저장소 · 버전 · index.md · log.jsonl |
| `lint.py` | 무결성 검사 (배포 게이트) |
| `retrieval.py` | BM25 ⊕ n-그램 → RRF |
| `review.py` | 검증 워크플로 · review.jsonl |
| `route.py` | ACL 우선 모델 라우팅 정책 |
| `assist.py` | 서술 초안 제안 — LLM 이 **말만** 쓰게 하는 세 겹 방어 |
| `cli.py` | `llmwiki wiki …` |

---

## 수치 검산이 실질이다

계산만 하면 "우리 계산은 이렇다" 로 끝난다. **검산**을 하면 원문이 틀렸다는 것을 잡는다.

`extract.py` 는 두 곳에서 원문의 수치를 얻는다.

1. **표** — 연간 전력량 산정표, 사업 전·후 집계표, 투자비 표
2. **본문 계산식** — 보고서는 식을 그대로 적는다

```
= 36(㎏/h) × 10(h/d) × 300(d/y) × 70(%) = 75,600(㎏)
   └────────── 입력 ──────────┘            └ 원문의 결과 ┘
```

곱을 다시 계산해 결과와 대조하면 그 자리에서 검산이 된다. 실제 진단 보고서
(비이테크, 2026-04, 32면)에 돌린 결과:

| | 건수 |
|---|---|
| 검산 | 46 |
| **불일치** | **3** |

셋 다 원문의 오류였다.

| 위치 | 원문 | 재계산 | 무엇이 틀렸나 |
|---|---|---|---|
| 집계표 전기 온실가스량 증감 | −2,095.16 | −1,756.86 | 169.15 − 1,926.01 이 아니다 |
| 집계표 LPG 온실가스량 증감 | 838.28 | 397.08 | 617.68 − 220.60 이 아니다 |
| 본문 가동시간 | 3,600 (y) | 3,000 | 10(h) × 300(d) = 3,000 |

허용오차는 두 겹이다. 상대 0.5%(`units.yaml`)와 **원문이 적은 자릿수**. 보고서가
4.572 를 `4.6(년)` 으로 적는 것은 오류가 아니라 표기다. 자릿수까지 맞으면 통과시킨다.

검산에 실패한 값을 인용하는 페이지는 `numeric_verified: false` 로 남고, 서비스 응답의
인용 대상에서 빠진다. 승인하려면 검토자가 **미검산을 명시적으로 인지**해야 한다.

---

## 계수는 코드에 없다

```yaml
- code: lpg.tco2eq_per_ton
  value: 2.918
  unit: tCO2eq/ton          # ★ 분모는 toe 가 아니라 LPG 1톤이다
  valid_until: "2026-12-31"
  mislabeled_as: tCO2eq/toe  # 원문이 자주 틀리게 적는 표기
```

`calc.py` 에는 계수 리터럴이 하나도 없다(`test_factors_live_in_yaml_not_in_code` 가
AST 로 고정한다). 개정이 오면 고칠 곳이 한 군데다.

`mislabeled_as` 는 실제 사고를 막는 장치다. 이 보고서는 `2.918(tCO2eq/toe)` 라고 적고
실제로는 톤에 곱했다 — 값은 맞고 라벨이 틀렸다. 그대로 두면 다음 사람이 라벨대로
toe 에 곱해 배출량을 20% 부풀린다. lint 의 `unit.label_mismatch` 가 이 표기를 잡는다.

`valid_until` 은 개정 미반영을 막는다. 만료가 90일 안이면 lint 가 경고한다.

---

## 데이터 컨트랙트

```yaml
stable_id: ecm-rotary-disc-dryer
type: measure                    # 9종 닫힌 집합
version: 1
content_hash: sha256:bed16cd5…   # 본문이 바뀌면 검토가 무효가 된다
source_span:                     # 근거 없는 페이지는 인용될 수 없다
  - doc: 에너지진단 보고서_비이테크(최종).pdf
    pages: [18, 19]
    section: Ⅲ 세부개선사항
acl: internal                    # public < internal < confidential < restricted
provenance: {ingested_by, ingested_at, pipeline_version}
owner: energy-team
status: draft                    # draft | reviewed | deprecated
domain: industrial
measurement_basis: mixed         # measured | documented | estimated | design | mixed
confidence: medium
numeric_verified: true           # ★ calc.py 검산 통과 여부
tags: [개선안, ESCO, industrial]
related: [reg-energy-unit-price, reg-ghg-emission-factor]
```

`measurement_basis` 는 `kb` 의 근거 등급(derivation)과 1:1 로 대응한다
(`BASIS_FROM_DERIVATION`). 두 계층이 같은 사실을 다른 이름으로 부르면 추적이 끊긴다.

### ★ ID 는 ASCII 이고 사업장 키는 사람이 정한다

`stable_id` 는 파일명·URL·TTL·그래프 키로 동시에 쓰인다. 한글 ID 는 어딘가에서 반드시
깨지고, 깨지면 링크가 통째로 끊긴다. 그래서 `terms.py` 가 한글 명칭을 ASCII 로 옮기고,
**사전에 없으면 번역을 지어내지 않는다** — 짧은 해시와 `needs_naming` 을 남겨 사람이
이름을 붙이게 한다. 지어낸 번역은 같은 설비가 보고서마다 다른 ID 를 받게 만들어
ECM 재사용이라는 목적 자체를 무너뜨린다.

사업장 키(`--site vitech`)도 사람이 정한다. 문서 해시에서 뽑으면 보고서를 재발행하는
순간 ID 가 전부 갈린다.

---

## ACL 과 링크 방향

| 타입 | 등급 | 이유 |
|---|---|---|
| 원문 · 진단 · 사업장 · 설비 · 지표 | `confidential` | 고객사 설비·사용량·계약 정보 |
| 개선안(ECM) · 인사이트 | `internal` | 사업장 식별정보를 담지 않는 재사용 자산 |
| 법규·계수 | `public` | 공개 정보 |

**낮은 등급이 높은 등급을 참조하면 위반이다.** 링크 자체가 존재와 맥락을 흘리기
때문이다. 그래서 ECM 카드는 진단 건을 직접 링크하지 않는다 — 진단 페이지가 카드를
걸고, 화면이 **역링크**로 사례를 보여 준다. 이 규칙을 어기면 lint 가 `blocker` 를 내고
배포가 막힌다(`deployable=False`).

---

## Lint

| 검사 | 코드 | 심각도 |
|---|---|---|
| 필수 필드 누락 | `schema.*` | error |
| stable_id 중복 | `id.duplicate` | **blocker** |
| ACL 상속 위반 | `acl.inheritance` | **blocker** |
| 끊어진 링크 | `link.broken` | error |
| 고아 페이지 | `link.orphan` | warning |
| 수치 검산 실패 | `numeric.unverified` | warning |
| 단위 라벨 오기 | `unit.label_mismatch` | warning |
| 계수 만료 임박 | `regulation.expiring` | warning |
| 문서 간 모순(설비 제원) | `contradiction.equipment` | warning |
| 초안 · 검토 필요 표시 | `review.pending` · `review.marker` | info |

문서 간 모순은 **탐지**만 룰이 한다. 무엇이 맞는지는 사람이 정한다.

---

## 검증 워크플로

파이프라인이 만든 것은 전부 `draft` 로 태어난다. 세 가지를 강제한다.

1. **차단 위반이 있으면 승인할 수 없다.** ACL 위반·ID 중복은 사람이 넘길 수 있는
   종류가 아니다.
2. **검산 실패는 명시적으로 인지해야 승인된다.** 인공지능 기본법 제34조의 인적 감독은
   '눌렀다' 가 아니라 '보고 판단했다' 여야 한다.
3. **본문이 바뀌면 검토가 무효다.** 저장소가 상태를 `draft` 로 되돌린다.

`review.jsonl` 은 덧붙이기뿐이다. 결정은 덮어쓰이지 않고 쌓인다.

---

## 검색

```
Score_RRF(d) = Σ  w_i / (60 + rank_i(d))
              i∈{bm25, ngram}
```

| 채널 | 역할 |
|---|---|
| `bm25` | 정확 표기 — 모델명(`SP 125V`), 조항 번호, 사업장명 |
| `ngram` | 표기 흔들림 — `루츠블로워` ↔ `루츠 블로워` ↔ `루츠부로워` |

세 표기가 **같은 보고서 안에** 섞여 있다. 두 번째 채널을 dense 라 부르지 않은 이유는,
그렇게 부르면 다음 사람이 임베딩이 이미 있다고 믿기 때문이다. 임베딩이 생기면 채널
하나를 더 끼우면 되고, 그때는 **이 베이스라인 대비 성능으로** 평가한다.

ACL 필터는 화면 문구가 아니라 **코드**가 건다.

---

## 모델 라우팅

```
if acl in {confidential, restricted}:  → 사내 모델 전용 (외부 호출 차단)
else:                                  → 태스크 난이도로 2차 판정
```

순서를 뒤집으면 "이건 어려우니까 외부로" 가 `confidential` 문서에도 적용된다.
모르는 태스크는 **막히는 쪽으로** 틀린다.

---

## LLM 을 부르는 유일한 자리 — 서술 초안 제안

`assist.py` 가 개선안 카드의 `[검토 필요]` 자리(적용 조건의 일반화)에 **문장**을
제안한다. 수치는 여전히 코드만 만든다. 세 겹으로 막는다.

1. **ACL 이 경로를 정한다.** `route.decide()` 가 판정하고 우회 인자는 없다.
2. **사내/외부는 화면에서 고르고, 기본은 사내다.** 고르지 않으면 사외로 나가지
   않는다. 등급이 허용해도 사용자가 사내를 골랐으면 사내로 간다 — 서버는 **넓히는
   방향으로만** 끼어든다. 반대로 등급이 막으면 외부를 골라도 사내로 되돌리고,
   응답의 `requested`·`overridden` 으로 그 사실을 알린다.
3. **출력에서 숫자를 검사한다.** 프롬프트로만 막으면 언젠가 샌다.

운영 서버에서 실제로 돌린 결과가 이 설계의 근거다.

| 페이지 | 등급 | `allow_external` | 실제 경로 | 출력 수치 검사 |
|---|---|---|---|---|
| `ecm-rotary-disc-dryer` | internal | 없음 | **거부** | — |
| `ecm-rotary-disc-dryer` | internal | 있음 | grok (4.2s) | **불합격** — `6000`, `70`, `30` 은 원문에 없다 |
| `dgn-vitech-2026-04` | confidential | 있음 | **ollama** (외부 차단) | **불합격** — `400000` 은 원문에 없다 |

두 모델 모두 그럴듯한 임계값을 지어냈다. 문장은 쓸 만했고 숫자는 아니었다 —
그래서 문장만 쓰게 하고 숫자는 검사한다. 제안은 페이지에 저장되지 않는다.

### 재분석 — 규칙이 만든 문장이 거칠 때

규칙 추출은 수치는 정확하지만 문장은 원문에서 잘라 붙인 조각이라 중간에서 끊긴다.
재분석은 그 페이지가 **인용한 쪽의 원문**을 함께 넣어 서술만 다시 쓰게 한다.

원문 발췌가 이 기능의 실질이다. 페이지 본문만 주면 모델은 이미 거칠어진 문장을 다시
다듬을 뿐, 빠진 맥락을 채우지 못한다. 그래서 `source_span` 이 가리키는 쪽의 채널
청크(지식 데이터베이스에 적재된 **비식별본**)만 골라 넣는다 — 문서 전체를 넣으면
32면짜리 보고서가 통째로 들어가 엉뚱한 쪽을 근거로 쓴다.

프롬프트는 **무엇을 반드시 고칠지**를 먼저 말한다. 보존 지시만 강하게 쓰면 모델이
몸을 사려 원문을 그대로 돌려주고, 그러면 재분석을 부른 이유가 사라진다. 실제로
그랬다 — 첫 판 프롬프트는 요약을 한 글자도 바꾸지 않고 돌려줬다.

반영에는 세 관문이 있다.

| 관문 | 왜 |
|---|---|
| 서명 필수 | 익명으로 확정되는 경로를 두지 않는다 |
| 수치 재검사 | **서술을 고치라고 부른 모델이 표의 수치를 바꾸는 것**이 이 기능의 가장 큰 위험이다 |
| 절 구조 검사 | 제목이 사라진 결과를 반영하면 페이지 형식이 무너진다 |

반영하면 버전이 오르고 상태가 `draft` 로 돌아간다 — 예전 서명이 새 문장을 보증하지
않기 때문이다. 결과는 화면에서 **편집 가능한 상태**로 보여 준다. 마지막 문장은
사람이 소유한다.

운영 서버(비이테크 진단서, `ecm-rotary-disc-dryer`)에서 실제로 돌린 결과:

```
before  3) 수직형 사이클론 회전식 디스크 건조기를 설치하여 저함수율(10~12%)까지
        균일 건조되도록, 함수율의 조정이 가능하고. 높은 품질의 건조품을 생산 .

after   음식물 폐기물 유기질 공정에서 기존 저효율 보일러와 루츠블로워를 이용한
        재래식 건조 시스템을 수직형 사이클론 회전식 디스크 건조기와 노통연관식
        폐열 보일러(3t)로 교체한다. 디스크 전체 면적을 전열면으로 활용하고 …
```

근거 p.18–19 (5,871자), 수치 검사 통과, 절 구조 유지, 9.5초.

---

## API

```
GET  /api/wiki/health                 상태 · 저장소 통계 · lint 요약 · 계수 만료
GET  /api/wiki/schema                 데이터 컨트랙트 닫힌 집합
GET  /api/wiki/units                  단위 SSOT
POST /api/wiki/preview                PDF → 페이지 초안 (저장하지 않는다)
POST /api/wiki/ingest                 PDF → 위키 저장 (게이트 통과 시에만)
GET  /api/wiki/pages?type=&status=&acl=
GET  /api/wiki/pages/{id}?acl=        페이지 + 역링크 + lint + 검토 이력
GET  /api/wiki/search?q=&acl=&type=   BM25 ⊕ n-그램 RRF
GET  /api/wiki/graph?acl=             페이지·링크 그래프
GET  /api/wiki/lint                   무결성 검사
GET  /api/wiki/review/queue           검증 큐
POST /api/wiki/review/{id}            검토 결정 (서명 필수)
GET  /api/wiki/review/journal         검증 저널
POST /api/wiki/assist                 서술 초안 제안 (ACL 라우팅 + 출력 수치 검사)
POST /api/wiki/reanalyze              원문 발췌를 근거로 페이지 재서술 (저장하지 않는다)
POST /api/wiki/pages/{id}/apply       재분석 결과 반영 (서명 · 수치/구조 재검사)
POST /api/wiki/calc                   수치 계산·검산
GET  /api/wiki/routing?task=&acl=     라우팅 정책
GET  /api/wiki/index.md               카탈로그
```

화면은 `/wiki` (열람) 과 `/admin` (관리자). 열람만 필요한 사람에게 업로드·검증 화면을
보여 주지 않는 것이 접근 통제의 첫 단계다.

---

## 실행

```bash
llmwiki wiki ingest 보고서.pdf --site vitech   # PDF → 위키
llmwiki wiki lint                              # 무결성 검사 (위반 시 종료코드 1)
llmwiki wiki queue                             # 검토 큐
llmwiki wiki verify ecm-rotary-disc-dryer -a kim --ack-unverified
llmwiki wiki search "폐열회수" --acl internal
llmwiki wiki units                             # 계수 SSOT · 만료 임박
llmwiki wiki routing --task report_draft --acl confidential
pytest tests/test_ediag.py tests/test_ediag_api.py -q
```

---

## 알려진 한계

| 한계 | 영향 | 계획 |
|---|---|---|
| 개선안별 경제성 분해가 없다 | ECM 카드의 절감효과가 **사업 전체 기준**이다 | 원문에 없는 값이라 사람 입력이 필요하다 |
| 적용 조건이 사례 1건 기준 | 일반화 조건이 비어 있다(`[검토 필요]`) | 사례 2건 이상 쌓이면 규칙으로 교차 |
| 두 번째 검색 채널이 임베딩이 아니다 | 동의어(`폐열회수`↔`이코노마이저`)에 약하다 | 임베딩 채널 추가 후 베이스라인 대비 평가 |
| 모순 탐지가 설비 제원뿐 | 수치 모순은 문서 내 검산으로만 잡는다 | 문서 간 수치 대조 |
| 스캔본 PDF 미지원 | 텍스트 레이어가 없으면 빈 결과 (`kb` 와 동일) | OCR |
| 그래프 뷰가 없다 | 링크 구조를 목록으로만 본다 | `/api/wiki/graph` 는 이미 있다 — 화면만 남았다 |
