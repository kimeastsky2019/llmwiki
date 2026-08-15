# LLMWiki

레거시 운영 소스(Java Spring + MyBatis)를 정적 분석 + LLM 으로 읽어
**프로그램 명세서를 자동 생성**하고, 이를 **검색 가능한 위키**로 서비스합니다.

```
운영 소스 ──▶ 정적 분석 ──▶ LLM 서술 생성 ──▶ MD 산출물 ──▶ 웹 뷰어
 (Java/XML)   (파서/그래프)    (Claude/Ollama)   (docs/*.md)   (FastAPI+React)
                    └──────────── CI/CD 배포 훅에서 매번 재실행 ────────────┘
```

기존 SI 산출물의 문제는 "만든 순간부터 낡는다" 입니다. 이 도구는 산출물을
**운영계로 소스를 넘기는 시점에 다시 만들어** 항상 운영 소스와 일치시킵니다.

---

## 설계 원칙: 사실과 서술을 분리한다

산출물이 거짓말을 하면 아무도 쓰지 않습니다. 그래서 역할을 나눴습니다.

| 항목 | 생성 주체 | 근거 |
|---|---|---|
| 호출 URL, 클래스 목록, 테이블, CRUD 매트릭스, SQL 원문, 호출 흐름도, 영향도 | **정적 파서** | 소스에서 기계적으로 추출 — 추측 없음 |
| 업무 설명, 처리 로직 서술, 파라미터 의미, 오류 처리, 개선 포인트 | **LLM** | 파서가 뽑은 사실만 컨텍스트로 제공 |

LLM 에게는 "확인되지 않으면 '소스상 확인 불가'로 쓰라"고 지시합니다.
흐름도(mermaid)는 LLM 이 그리지 않고 실제 호출 그래프에서 렌더링합니다.

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
    model: "qwen2.5-coder:32b"
    keep_alive: "30m"
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
    - rsync -a docs/ wiki@wiki-server:/srv/llmwiki/docs/
  only: [master]
```

`generate` 는 프로그램별 소스 해시를 프론트매터에 남기므로 **바뀐 프로그램만**
LLM 을 호출합니다. 1,000본짜리 시스템에서도 일상 배포 비용은 몇 건 수준입니다.

---

## 뷰어에서 할 수 있는 것

- 계층(기관계/채널계/공통) → 프로그램 트리 탐색
- 한글·영문 통합 검색 (업무명 / 테이블명 / 클래스명 / URL / 본문)
- 프로그램 명세서 열람 + 호출 흐름도(mermaid) 렌더링
- 테이블 클릭 → **이 테이블을 함께 쓰는 다른 프로그램**(영향도)
- 원본 소스 인라인 열람
- **Excel 내려받기** (개요 / 클래스 / CRUD / SQL / 영향도 / 소스 시트)

---

## 구조

```
llmwiki/
  parsers/
    scanner.py    주석·문자열 제거 (중괄호 매칭이 깨지지 않도록)
    java.py       클래스/메서드/필드/어노테이션/호출 추출
    mybatis.py    Mapper XML → SQL, 테이블, CRUD, 파라미터
    graph.py      호출 그래프 · 프로그램 단위 · 영향도
  llm/            claude | ollama | template 공급자
  docgen/         프롬프트 + MD 렌더링(부록은 파서가 직접 작성)
  server/         FastAPI · 검색 · Excel
web/              React 뷰어
sample/           예제 Spring+MyBatis 소스
tests/            파서 회귀 테스트
```

---

## 제약과 다음 단계

**현재 다루는 범위**
- Spring MVC(`@Controller`/`@RestController`) + MyBatis Mapper XML / 인터페이스
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
