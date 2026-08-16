# LLMWiki

운영 소스(Java Spring+MyBatis / Python FastAPI·Flask+SQLAlchemy·rdflib)를
정적 분석 + LLM 으로 읽어
**프로그램 명세서를 자동 생성**하고, 이를 **검색 가능한 위키**로 서비스합니다.

```
운영 소스 ──▶ 정적 분석 ──▶ LLM 서술 생성 ──▶ MD 산출물 ──▶ 웹 뷰어
(Java/XML/py)  (파서/그래프)    (Claude/Ollama)   (docs/*.md)   (FastAPI+React)
                    └──────────── CI/CD 배포 훅에서 매번 재실행 ────────────┘
```

기존 SI 산출물의 문제는 "만든 순간부터 낡는다" 입니다. 이 도구는 산출물을
**운영계로 소스를 넘기는 시점에 다시 만들어** 항상 운영 소스와 일치시킵니다.

| 문서 | 내용 |
|---|---|
| [서비스 기획서](design/서비스기획서.md) | 문제 정의 · 타깃 · 기능 범위 · 사업 모델 · 리스크 |
| [온톨로지 스키마 v1.0.0](design/온톨로지-스키마.md) | 노드 11종 · 관계 19종 · 식별자 규칙 · 검증 규칙 (확정) |
| [규제 지식그래프 v1.0.0](design/규제-지식그래프.md) | 근거기반 자동평가 엔진 · 권한 3분할 · 커밋 결재 (확정) |

---

## 설계 원칙: 사실과 서술을 분리한다

산출물이 거짓말을 하면 아무도 쓰지 않습니다. 그래서 역할을 나눴습니다.

| 항목 | 생성 주체 | 근거 |
|---|---|---|
| 호출 URL, 클래스 목록, 테이블, CRUD 매트릭스, SQL 원문, 호출 흐름도, 영향도 | **정적 파서** | 소스에서 기계적으로 추출 — 추측 없음 |
| 업무 설명, 처리 로직 서술, 파라미터 의미, 오류 처리, 개선 포인트 | **LLM** | 파서가 뽑은 사실만 컨텍스트로 제공 |

LLM 에게는 "확인되지 않으면 '소스상 확인 불가'로 쓰라"고 지시합니다.
흐름도(mermaid)는 LLM 이 그리지 않고 실제 호출 그래프에서 렌더링합니다.

이 분리는 말이 아니라 [온톨로지 스키마](design/온톨로지-스키마.md)에 박혀 있습니다.
모든 사실에 `derivation` 이 붙습니다 — `static`(파서) / `derived`(계산) / `llm`(서술).
샘플 기준 노드 146개 중 **144개가 `static`** 입니다. 감리에서 "어디까지 믿을 수 있나"를
물으면 `llm` 절만 검토 대상이라고 답할 수 있습니다.

---

## 빠른 시작

```bash
uv venv --python 3.12
uv pip install -e ".[dev]"

# 1) 소스 정적 분석
uv run llmwiki parse

# 2) 산출물 생성 (LLM 없이 구조만 보려면 provider=template)
export ANTHROPIC_API_KEY=sk-ant-...
uv run llmwiki generate

# 3) 뷰어 빌드 + 기동
cd web && npm install && npm run build && cd ..
uv run llmwiki serve       # http://127.0.0.1:8722
```

`sample/` 에 고객관리(기관계) / 계좌조회(채널계) 예제 소스가 들어 있어
설정 없이 바로 전체 흐름을 확인할 수 있습니다.

### 명령어

| 명령 | 설명 |
|---|---|
| `llmwiki parse` | 소스 스캔 → `docs/index.json` |
| `llmwiki programs` | 추출된 프로그램(산출물 단위) 목록 |
| `llmwiki generate [--only ID] [--force]` | LLM 으로 MD 생성. 소스 해시가 같으면 건너뜀 |
| `llmwiki serve [--reload]` | 위키 서버 |
| `llmwiki pipeline` | parse + generate (CI 용, 실패 시 exit 1) |
| `llmwiki ontology show` | 확정 스키마(노드·관계) 보기 |
| `llmwiki ontology validate` | 산출물이 스키마를 지키는지 검사 (위반 시 exit 1) |
| `llmwiki ontology export [--graph]` | 스키마 또는 분석 결과 그래프를 JSON 으로 |

---

## 규제 지식그래프 — 근거기반 자동평가

같은 원칙(사실과 서술을 분리한다)을 규제 준수 평가에 적용한 하위 시스템입니다.
한 줄로는 **"LLM은 그래프를 채우고, 판정은 그래프 위의 룰이 한다."**

설계는 [규제 지식그래프 문서](design/규제-지식그래프.md)에, 스키마의 단일 원본은
`llmwiki/compliance/ontology.py` 에 있습니다.

```bash
uv run llmwiki reg seed        # 데모 데이터 적재 (커밋 결재 경로를 그대로 지나갑니다)
uv run llmwiki reg validate    # 승인 그래프가 스키마·헌법 셋을 지키는지
uv run llmwiki reg assess      # 판정 — LLM 을 호출하지 않습니다
uv run llmwiki reg coverage    # 통제하지 않고 있는 규제 의무
uv run llmwiki reg goldset     # 커버리지와 정밀도를 나눠서 측정
```

`reg assess` 는 시드 데이터에서 커버리지 50% · 정밀도 100% 를 냅니다. 나머지 50% 는
틀린 것이 아니라 **판단 유보**로 사람에게 넘긴 것입니다. 애매한 것을 자동 처리하면
심사자가 물량에 압도되고, 그러면 형식 승인이 나서 통제 실효성 자체가 무너집니다.

| 명령 | 설명 |
|---|---|
| `llmwiki reg schema` | 규제 온톨로지(노드 13종·관계 14종·유보 트리거) 보기 |
| `llmwiki reg seed` | 데모 데이터 적재 |
| `llmwiki reg graph [--as-of]` | 승인 그래프 요약 (과거 시점으로 되돌리기) |
| `llmwiki reg validate` | 형상·근거 스팬·인용 강도·저널 검사 (위반 시 exit 1) |
| `llmwiki reg assess [--service] [--commit]` | 판정. `--commit` 이면 PROV 계보와 함께 그래프에 기록 |
| `llmwiki reg confirm <uuid> --by <agent>` | 확정 서명 (게이트 3) |
| `llmwiki reg coverage` | 커버리지 갭 · 수기 의존 통제 |
| `llmwiki reg impact <조문uuid>` | 규제 변경 영향분석 |
| `llmwiki reg goldset` | 골드셋 회귀 (커버리지 · 정밀도 · Cohen κ) |
| `llmwiki reg ingest <파일> --uuid ... --name ...` | 규제 문서(docx·xlsx·pdf·txt)를 조문 단위로 수집 (L0) |
| `llmwiki reg template <통제> <서식>` | 회사 서식에서 필수 절을 뽑아 구성 검토 절차 생성 |
| `llmwiki reg submit <작업물> --uuid ...` | 직원 작업물을 증적으로 적재 (절·미기입 자리 기록) |
| `llmwiki reg consistency` | 문서 간 정합성 — 같은 값을 다르게 적은 곳 |
| `llmwiki reg link <작업물> --service ...` | 사내 sLM 이 증적 연결 **제안** |
| `llmwiki reg propose [--llm]` | 조문에서 의무 추출 **제안** (L1) |
| `llmwiki reg link-programs` | LLMWiki 가 뽑은 운영 프로그램 → 증적 생산 기능 |
| `llmwiki reg changes list \| show \| approve \| reject` | 커밋 결재 (L6) |

뷰어에서는 좌측 하단 **규제 준수 평가 열기 →** (`/reg`) 로 들어갑니다.

| 탭 | 보여 주는 것 |
|---|---|
| 판정 | 서비스 × 통제별 판정, 유보 사유, 근거 증적과 재현용 4개 버전, 확정 서명 |
| 커버리지 갭 | 통제 없는 의무 · 부분만 덮는 통제 · 수기 의존 통제 |
| 커밋 결재 | 제안 목록(등급·상태·영향), diff, 게이트가 막은 사유, 승인/반려 |
| 그래프 | 노드 집계 · 스키마 검증 · 골드셋 회귀 |

API 는 `/api/reg/…` 로 열려 있습니다. 승인 그래프를 움직이는 경로는 **결재와 확정
서명 둘뿐**이며, 노드를 직접 만들거나 지우는 엔드포인트는 없습니다. 화면도 같은
경로를 씁니다 — UI 가 우회로를 만들지 않습니다.

### 세 개의 헌법

| 원칙 | 강제 방식 |
|---|---|
| **근거 없는 사실 금지** | 문서 유래 사실은 원문 스팬 필수. `문서[start:end] == 인용문` 을 기계가 대조하므로, 지어낸 근거는 오프셋이 맞지 않아 제안 단계에서 버려집니다 |
| **삭제 없음** | 저장소가 append-only 저널이라 삭제 연산이 없습니다. `obsolete` + `replaced_by` 만 허용 |
| **판정 재현성** | 모든 판정이 온톨로지·룰셋·기준·조문 4개 버전을 기록. `--as-of` 로 과거 그래프를 그대로 되살립니다 |

여기에 **인용 강도** 검증이 붙습니다. 조문이 "공개하도록 노력하여야 한다"(권고)인데
제안이 "필수 의무"라고 말하면, 문장은 인용했지만 주장이 근거를 넘어선 것입니다.
`주장 강도 ≤ 근거 강도` 를 요구해 이런 제안을 사람 앞에 보내지 않습니다.

### 문서와 작업물 검토

규제 문서만이 아니라 **직원이 만든 산출물**도 같은 그래프에 들어옵니다.
`.docx` · `.xlsx` · `.pdf` 를 평문 + 절 + 문자 오프셋으로 바꾸므로, 근거 스팬이
코드에서와 똑같이 동작합니다.

검토하는 것은 **구성이지 내용이 아닙니다.**

| 검사 | 방법 |
|---|---|
| 요구된 절이 있는가 | 회사 서식(별첨01~15)을 파싱해 필수 절을 뽑습니다. **체크리스트를 손으로 만들지 않습니다** — 서식이 개정되면 다시 뽑아 결재에 올리면 됩니다 |
| 서식을 실제로 채웠는가 | `……`, `YYYY.MM.DD`, `예시)` 같은 자리표시자가 남아 있으면 판단유보 |
| 문서끼리 말이 맞는가 | 기획서 임계치 0.75 vs 검증결과서 0.70 같은 불일치. 숫자·날짜·예아니오만 대조하고 자유 서술은 건드리지 않습니다 |

내용의 적정성("이 위험평가가 충실한가")은 판정하지 않습니다. LLM 이 사람의 작업물을
채점하면 이 설계가 거부한 LLM-as-judge 를 다시 들이는 것이라, 그 판단은 사람 몫으로
남기고 룰은 판단유보로 넘깁니다.

**Word 자동 번호 복원** — 실제 규정 문서에는 본문에 "제1조" 라는 글자가 없습니다.
Word 가 스타일 번호매기기로 화면에만 그립니다. `styles.xml → numbering.xml` 을
따라가 번호를 재구성하지 않으면 조문 앵커 자체를 만들 수 없습니다.

### ★ 조문 앵커 — 단일 실패 지점

법령이 개정되며 "제13조" 가 "제13조의2" 로 분화되면, 조문 번호를 식별자로 쓴 매핑은
전부 깨집니다. 그래서 조문 ID 는 **불변 UUID** 이고 번호는 속성입니다. 분화는
`SPLIT_INTO` 계보로 잇습니다. 이 결정은 `tests/test_compliance_ontology.py` 가 지킵니다.

실제 규정 문서를 넣어 보니 이유가 하나 더 있었습니다. **조 번호는 절마다 1부터 다시
시작합니다** — 실측한 규정 한 건에 "제1조" 가 **14개** 있었습니다. 번호는 문서 안에서도
유일하지 않으므로, 앵커는 `제2장/제2절/제1조` 같은 **절 경로**에서 유도합니다.

---

## 설정 (`config.yaml`)

```yaml
project:
  name: "여신관리시스템"
  source_roots: ["/svn/checkout/loan"]
  layers:                                  # 뷰어 좌측 트리 1단
    - { name: "기관계", match: "**/inst/**" }
    - { name: "채널계", match: "**/channel/**" }

llm:
  provider: claude          # claude | ollama | template
  claude:
    model: claude-opus-5
    effort: high            # low | medium | high | xhigh | max
    concurrency: 4
  ollama:                   # 망분리 반입용
    base_url: "http://211.119.38.216:11434"
    model: "hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:Q4_K_M"
    keep_alive: "30m"

output:
  docs_dir: "./docs"
  language: ko              # ko | en — 산출물 생성 언어 + 뷰어 초기 언어
```

`provider` 한 줄만 바꾸면 개발/데모(Claude API) ↔ 고객사 사내망(Ollama) 전환이 됩니다.
환경변수 `LLMWIKI_PROVIDER` 로도 덮어쓸 수 있습니다.

> **금융/공공 소스는 클라우드 API 로 보내지 마십시오.** 데모는 `sample/` 로,
> 실제 고객 소스는 `provider: ollama` 로 사내 GPU 서버에서 돌리는 것을 전제로 설계했습니다.

---

## CI/CD 연동 — 산출물 자동 최신화

배포 파이프라인에서 소스 취약점 점검 다음, 운영계 반영 직전에 붙입니다.

```yaml
# .gitlab-ci.yml 예시
generate-docs:
  stage: deploy
  script:
    - uv pip install -e .
    - uv run llmwiki pipeline          # 변경된 프로그램만 재생성
    - uv run llmwiki ontology validate # 산출물이 스키마를 지키는지 (위반 시 실패)
    - rsync -a docs/ wiki@wiki-server:/srv/llmwiki/docs/
  only: [master]
```

`generate` 는 프로그램별 소스 해시를 프론트매터에 남기므로 **바뀐 프로그램만**
LLM 을 호출합니다. 1,000본짜리 시스템에서도 일상 배포 비용은 몇 건 수준입니다.

---

## 뷰어에서 할 수 있는 것

- **로컬 폴더 불러오기** — 아래 참조
- 계층(기관계/채널계/공통) → 프로그램 트리 탐색
- 한글·영문 통합 검색 (업무명 / 테이블명 / 클래스명 / URL / 본문)
- 프로그램 명세서 열람 + 호출 흐름도(mermaid) 렌더링
- 프로그램별 **명세서 생성 / 재생성** 버튼 (LLM 호출을 화면에서)
- 테이블 클릭 → **이 테이블을 함께 쓰는 다른 프로그램**(영향도)
- **소스 브라우저** — 아래 참조
- **Excel 내려받기** (개요 / 클래스 / CRUD / SQL / 영향도 / 소스 시트)

### 로컬 폴더 불러오기

`config.yaml` 을 고치지 않고, 뷰어에서 내 컴퓨터의 소스 폴더를 열어 바로 분석합니다.
좌측 상단 **프로젝트 → ＋ 로컬 폴더 열기**.

브라우저의 기본 폴더 선택창은 보안상 실제 절대경로를 주지 않아 쓸 수 없습니다.
서버가 로컬에서 도는 점을 이용해 **탐색기를 직접 만들었습니다.**

```
┌─ 로컬 폴더 열기 ─────────────────────────────────────────────┐
│ /Users/me/workspace                                  [이동]  │
├───────────────┬──────────────────────────────────────────────┤
│ 바로가기      │ me / workspace / loan      [이 폴더에서 찾기] │
│  홈           ├──────────────────────────────────────────────┤
│  바탕화면     │ ⬆ 상위 폴더                                  │
│  문서         │ 📁 loan-batch          git   Java 210 · XML 44│
│ 최근          │ 📁 loan-web       maven git  Java 380 · XML 91│
│  loan         │ 📁 docs                                      │
│ 폴더          │                                              │
│  ▾ me         │                                              │
│    ▾ workspace│                                              │
│      · loan   │                                              │
├───────────────┴──────────────────────────────────────────────┤
│ /Users/me/workspace/loan                                     │
│ Java 590 · XML 135 · git   ↑↓ 이동·Enter·Backspace [이 폴더 분석]│
└──────────────────────────────────────────────────────────────┘
```

- **바로가기** — 홈 / 바탕화면 / 문서 / 다운로드 (있는 것만)
- **최근** — 분석했던 폴더 (브라우저에 저장)
- **폴더 트리** — 현재 경로가 자동으로 펼쳐지고, 하위는 누를 때 받아옵니다
- **브레드크럼** — 경로 어느 단계로든 한 번에
- **필터** — 현재 폴더의 하위 폴더 이름으로
- **키보드** — `↑`/`↓` 이동, `Enter` 들어가기, `Backspace` 상위, `Esc` 닫기
- **표식** — `maven` `gradle` `ant` `git` `svn` `webapp` 을 최상위에서만 판별해
  배지로 붙입니다. 하위까지 뒤지면 온통 배지가 돼 신호가 안 됩니다.
- 폴더마다 `Java n · XML n` 을 미리 세어 보여 줍니다. 큰 폴더는 도중에 세기를
  멈추고 `12+` 처럼 표시합니다 — 0건으로 잘못 단정하지 않습니다.
- 경로를 이미 알고 있으면 상단 입력창에 붙여넣고 Enter.

폴더를 고르면 **정적 분석까지 자동**으로 돌고, LLM 명세서는 프로그램 화면의
**명세서 생성** 버튼으로 따로 만듭니다. 큰 저장소에서 API 비용이 갑자기 튀지
않게 하려는 의도입니다.
- 불러온 프로젝트는 목록에 남아 상단에서 전환합니다. 프로젝트마다
  `projects/<id>/docs` 와 `index.json` 을 따로 두므로 산출물이 섞이지 않습니다.
- 목록에서 제거해도 **원본 소스는 건드리지 않습니다.** 지우는 것은
  `projects/<id>/` 아래 생성 산출물뿐입니다.

`.git` · `node_modules` · `.venv` · `target` · `build` 같은 디렉터리는 스캔·열람
양쪽에서 아예 들어가지 않습니다. 이게 없으면 임의의 로컬 폴더를 열었을 때
파일 수십만 개를 헤매느라 응답이 수십 초로 뜁니다.

탐색 범위는 기본이 홈 디렉터리입니다. 넓히거나 좁히려면:

```yaml
server:
  browse_roots: ["~/workspace", "/svn/checkout"]
```

> 이 탐색기는 서버가 도는 머신의 파일 목록을 노출합니다. 기본 바인드가
> `127.0.0.1` 인 것을 전제로 한 기능이니, 외부에 열어 서비스할 때는
> `browse_roots` 를 실제 소스 경로로 좁히십시오.

### 소스 브라우저

명세서를 읽다가 "실제 코드는 어떻게 생겼나"를 바로 확인하는 창입니다.
좌측 하단 **소스 브라우저 열기**, 명세서의 *분석 대상 소스* 파일, 테이블 상세의
SQL 파일 경로 — 어디서든 열립니다. (`Esc` 로 닫힘)

- `source_roots` 전체를 파일 트리로 탐색. `com/gng/inst` 처럼 자식이 하나뿐인
  디렉터리는 한 줄로 접어 Java 패키지 깊이에 파묻히지 않게 했습니다.
- 파일 경로 검색 / 파일 내 검색(이전·다음 이동, Enter·Shift+Enter)
- 줄번호 + 구문 강조 (Java / XML / SQL / properties / YAML / JSON)
  — 망분리 반입을 전제로 **외부 하이라이터 없이** 직접 구현했습니다
- 초록 점 = 정적 분석에 실제로 쓰인 파일(.java/.xml)

파일은 `source_roots` 안으로만 읽습니다. 상위 경로(`../`)·심볼릭 링크·2MB 초과
파일·바이너리는 서버에서 차단합니다.

---

## 다국어 (한국어 / English)

`output.language` 한 줄로 **산출물이 생성되는 언어**가 바뀝니다.
프롬프트·템플릿·MD 부록 제목·Excel 시트명이 모두 따라갑니다.

```bash
LLMWIKI_LANG=en uv run llmwiki generate --force
```

뷰어는 우상단 `KO / EN` 토글로 전환하며, 선택은 브라우저에 저장됩니다.
저장된 선택이 없으면 `output.language` 를 따릅니다. 서버 오류 메시지도 같은
언어로 내려옵니다.

문서 본문의 언어는 **생성 시점에 고정**되므로(프론트매터의 `language`),
UI 를 EN 으로 바꿔도 이미 한국어로 만든 명세서는 한국어 그대로 보입니다.
Excel 시트명은 UI 가 아니라 그 문서가 생성된 언어를 따릅니다.

---

## 구조

```
llmwiki/
  parsers/
    scanner.py    주석·문자열 제거 (중괄호 매칭이 깨지지 않도록)
    java.py       클래스/메서드/필드/어노테이션/호출 추출
    mybatis.py    Mapper XML → SQL, 테이블, CRUD, 파라미터
    python.py     ast 기반 파이썬 파서 (모듈/클래스/라우트/호출)
    pydata.py     SQLAlchemy · 원시 SQL · SPARQL 접근 지점 추출
    graph.py      호출 그래프 · 프로그램 단위 · 영향도
  llm/            claude | grok | ollama | template 공급자
  docgen/         프롬프트 + MD 렌더링(부록은 파서가 직접 작성)
  compliance/     규제 지식그래프 · 근거기반 자동평가
    ontology.py   규제 스키마 v1.0.0 (노드 13종·관계 14종) — 단일 원본
    docparse.py   docx·xlsx·pdf → 평문+절+오프셋 (Word 자동 번호 복원)
    template.py   회사 서식 → 필수 절, 자리표시자(미기입) 검출
    consistency.py 문서 간 정합성 — 같은 값을 다르게 적은 곳
    spans.py      근거 스팬 대조 + 인용 강도 (환각을 막는 두 겹)
    store.py      append-only 저널 · 승인본/제안본 분리 · as_of 재현
    changeset.py  커밋 결재 — 등급 G1~G4 · 영향분석 · 승인/반려
    rules.py      결정론적 판정 엔진 (이 파일에 LLM 이 없다)
    verify.py     형상 검증 · 골드셋 회귀 · Cohen κ
    analysis.py   커버리지 갭 · 규제 변경 영향 · 수기 의존 통제
    propose.py    조문 수집 · sLM 의무 제안 · LLMWiki Program 연계
    seed.py       데모 데이터 (샘플 규제 원문 포함)
  server/
    app.py        FastAPI 라우트 (프로젝트별로 인덱스·문서를 갈라 서비스)
    compliance.py 규제 API (/api/reg/…) — 쓰기는 결재·확정 서명뿐
    jobs.py       파싱·생성 백그라운드 작업 추적
  workspace.py    프로젝트 레지스트리 · 로컬 폴더 탐색기
  ontology.py     확정 스키마 v1.0.0 + 검증기 + 그래프 내보내기
  i18n.py         ko/en 문자열 (산출물·Excel·서버 메시지)
web/
  src/i18n.ts     뷰어 UI 문자열 + 언어 토글
  src/highlight.ts  의존성 없는 구문 강조
  src/SourceBrowser.tsx  소스 브라우저
  src/Projects.tsx  프로젝트 전환기 + 폴더 선택기
sample/           예제 Spring+MyBatis 소스
sample_py/        예제 FastAPI+Flask+SQLAlchemy+SPARQL 소스
projects/         뷰어로 불러온 로컬 프로젝트 (gitignore)
tests/            파서 회귀(Java/Python) · 다국어 · 소스 API · 온톨로지 · 워크스페이스
                  · 규제 온톨로지 · 판정 엔진 · 규제 API
design/           서비스 기획서 · 온톨로지 스키마 · 규제 지식그래프 문서
compliance/       승인 저널 · 변경 제안 · 원문 · 골드셋 (gitignore, 백업 대상)
```

---

## 파이썬 지원 (FastAPI · Flask · SQLAlchemy · rdflib)

`.py` 파일은 정규식이 아니라 **표준 라이브러리 `ast`** 로 읽습니다. 문법을 정확히
파싱하므로 Java 파서에 있는 "특이한 코드는 놓칠 수 있다"는 제약이 없습니다.

| 파이썬 개념 | 산출물에서의 자리 |
|---|---|
| `@router.get("/x")` · `@app.route("/x", methods=[...])` | 호출 URL |
| `APIRouter(prefix=...)` · `Blueprint(url_prefix=...)` | URL 앞부분 (놓치면 주소가 반쪽) |
| `__tablename__` + `Column(...)` | 테이블 + 컬럼 |
| `db.add / query / delete`, 속성 변경 + `commit()` | CRUD 매트릭스 |
| `cursor.execute("SELECT …")` · `text(...)` | 원시 SQL (테이블은 SQL 파싱) |
| `graph.query("SELECT ?s …")` · `graph.update("INSERT DATA …")` | **온톨로지 클래스/그래프** + CRUD |
| 모듈 · 클래스 docstring 첫 줄 | 업무명 |

**프로그램 단위**는 Java(컨트롤러 1개)와 다릅니다. FastAPI 는 라우트를 모듈 하나에
수십 개씩 늘어놓는 일이 흔해서 — 실제로 `main.py` 한 파일에 69개가 몰린 사례가
있었습니다 — 라우트가 12개를 넘으면 **URL 의 업무 세그먼트**로 쪼갭니다.
`/api/v1/auth/...` 와 `/api/v1/assessments/...` 는 각각 다른 명세서가 됩니다
(`api`, `v1` 같은 껍데기 세그먼트는 건너뜁니다).

### 파이썬에서 특히 신경 쓴 것

- **모델은 다른 모듈에 있습니다.** `models/entities.py` 에 정의하고 `services/` 에서
  씁니다. 파일 단위로만 모으면 CRUD 가 통째로 빕니다 — 그래서 스캔을 두 번 합니다.
- **쓰기는 변수를 거칩니다.** `db.add(customer)` 의 `customer` 가 어느 모델인지
  함수 스코프에서 추적하지 않으면 CRUD 가 **R 만** 나옵니다.
- **UPDATE 는 호출이 아니라 대입입니다.** `user.name = x` 뒤에 `commit()` 이 있을
  때만 UPDATE 로 셉니다. 커밋 없는 대입까지 세면 과탐입니다.
- **테이블명 표기를 맞춥니다.** 원시 SQL 은 `TB_CUSTOMER`, ORM 은 `tb_customer` 로
  나와 같은 테이블이 둘로 갈라지면 영향도가 깨집니다.
- **유틸 모듈은 프로그램이 아닙니다.** 파이썬은 거의 모든 모듈이 '함수를 가진
  서비스'라, 데이터를 실제로 만지는 것만 독립 명세서로 만듭니다.

### 아직 못 하는 것

- Django (`urls.py` · Django ORM) — 규칙이 달라 별도 작업이 필요합니다
- 동적 라우트 등록(`app.add_api_route(...)`), 리플렉션으로만 이어지는 호출
- 타입힌트가 없는 코드의 호출 그래프는 Java 보다 성깁니다 (실측 55% 가 힌트 보유)
- SPARQL 은 코드 안 문자열만 봅니다. `.rq` 파일이나 런타임 조립 질의는 못 읽습니다

`sample_py/` 에 FastAPI + Flask + SQLAlchemy + SPARQL 예제가 들어 있습니다.

---

## 제약과 다음 단계

**현재 다루는 범위**
- Spring MVC(`@Controller`/`@RestController`) + MyBatis Mapper XML / 인터페이스
- FastAPI / Flask + SQLAlchemy / rdflib (위 '파이썬 지원' 참조)
- 레거시 DAO 의 `sqlSession.selectList("ns.id")` 직접 호출
- 프로그램 단위 = 컨트롤러 1개 (컨트롤러가 없는 서비스는 별도 프로그램)

**아직 안 되는 것**
- JSP/화면 설계서, Struts, EJB, 프로시저 내부 로직
- 리플렉션·동적 프록시로만 연결되는 호출
- 파서는 정규식 기반이라 극단적으로 특이한 코드는 놓칠 수 있습니다.
  `tests/test_parser.py` 에 실패 케이스를 추가하며 넓혀가는 것을 전제로 만들었습니다.

**설계 단계 확장 (녹취록에서 논의된 다음 사이클)**
분석(As-Is)은 소스라는 명확한 입력이 있지만 설계(To-Be)는 입력이 요구사항뿐이라
품질 편차가 큽니다. 그래서 프롬프트를 자유 서술로 받지 말고 **입력 폼(항목별 엑셀)**
으로 받아 평준화한 뒤 프롬프트로 변환하는 구조를 권장합니다.
현재 코드에서는 `docgen/prompts.py` 의 템플릿을 설계용으로 하나 더 만들고
`Program` 대신 요구사항 레코드를 입력으로 넣으면 같은 파이프라인을 재사용할 수 있습니다.

---

## 알려진 환경 이슈

Anaconda 기반 파이썬으로 venv 를 만들면 `_` 로 시작하는 `.pth` 파일을 건너뛰어
`uv pip install -e .` 후 `llmwiki` 명령이 `ModuleNotFoundError` 를 냅니다.
`uv run llmwiki ...` 로 실행하거나, Anaconda 가 아닌 파이썬으로 venv 를 만드십시오.

```bash
uv venv --python 3.12 --python-preference only-managed
```
