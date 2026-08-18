# 배포

운영 서버에 올라가 있는 구성 그대로다. 여기 파일들은 서버에 있는 것을 그대로
가져온 것이므로, 서버를 고쳤으면 여기도 같이 고쳐야 한다.

서비스 주소: 전용 도메인의 루트. 실제 호스트와 계정은 저장소에 적지 않는다
(공개 저장소다). 사내 위키나 운영 문서를 볼 것.

## 구성

```
브라우저 ──80──▶ nginx ──┬─ Host: 기존 도메인·IP ─▶ rag-ai-gov (그대로 둔다)
                         └─ Host: llmwiki 도메인 ─▶ llmwiki  127.0.0.1:8722
                                                   ├ 위키 뷰어    (SPA)
                                                   └ /api/reg/…   규제 지식그래프·판정
```

처음에는 전용 도메인이 없어 기존 서비스 아래 `/wiki/` 로 붙였다. 80 을 기존
서비스가 `default_server` 로 잡고 있고 443·별도 포트가 상위망에서 열리지 않는
환경이었기 때문이다. 도메인이 생긴 뒤로는 Host 로 갈라 **루트에서** 서빙한다 —
프론트를 `base "/"` 로 빌드할 수 있어 자산 경로가 단순해진다. 옛 `/wiki/` 링크는
도메인으로 301 시킨다 (`llmwiki-app.conf`).

llmwiki 서버 블록에는 `default_server` 를 붙이지 않는다. 그래야 IP 로 들어온
요청이 종전대로 기존 서비스로 간다.

| 파일 | 배치 위치 |
|---|---|
| `nginx/llmwiki-site.conf` | `/etc/nginx/sites-available/llmwiki.conf` (+ sites-enabled 링크) |
| `nginx/llmwiki-app.conf` | `/etc/nginx/snippets/llmwiki-app.conf` — 옛 `/wiki/` 301 |
| `systemd/llmwiki.service` | `/etc/systemd/system/llmwiki.service` |
| `config.server.yaml` | `/opt/llmwiki/config.yaml` |
| `llmwiki.env.example` | `/etc/llmwiki/llmwiki.env` (키를 채워서) |

## 설치

```bash
# 1) 서비스 계정과 디렉터리
sudo useradd --system --home-dir /opt/llmwiki --shell /usr/sbin/nologin llmwiki
sudo mkdir -p /opt/llmwiki/{docs,projects,uploads,sources,compliance} /etc/llmwiki
sudo chown -R llmwiki:llmwiki /opt/llmwiki

# 2) 코드 (web/dist 는 로컬에서 빌드해 올린다 — 서버에 node 가 없다)
#    전용 도메인 루트에서 서빙하므로 base 는 기본값 "/" 이다.
#    (하위 경로로 붙일 때만 VITE_BASE 를 준다)
cd web && npm run build && cd ..
rsync -a --exclude __pycache__ --exclude '* 2.*' llmwiki pyproject.toml <서버>:/tmp/up/
rsync -a --delete web/dist/ <서버>:/tmp/up/dist/
# 서버에서:
sudo rsync -a --delete /tmp/up/llmwiki/ /opt/llmwiki/llmwiki/
sudo rsync -a --delete /tmp/up/dist/ /opt/llmwiki/web/dist/

# 3) 파이썬 환경
sudo -u llmwiki python3 -m venv /opt/llmwiki/.venv
cd /opt/llmwiki && sudo -u llmwiki .venv/bin/pip install -e .

# 4) 설정과 키
sudo cp config.server.yaml /opt/llmwiki/config.yaml
sudo install -o root -g llmwiki -m 640 llmwiki.env /etc/llmwiki/llmwiki.env

# 5) 서비스
sudo cp systemd/llmwiki.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now llmwiki

# 6) nginx — 전용 도메인 서버 블록
sudo cp nginx/llmwiki-site.conf /etc/nginx/sites-available/llmwiki.conf
sudo ln -sfn /etc/nginx/sites-available/llmwiki.conf /etc/nginx/sites-enabled/
#    옛 /wiki/ 링크를 살리려면 기존 앱 설정에서 include 한다
sudo cp nginx/llmwiki-app.conf /etc/nginx/snippets/
#   /etc/nginx/snippets/rag-ai-gov-app.conf 안에 아래 한 줄 추가:
#     include /etc/nginx/snippets/llmwiki-app.conf;
sudo nginx -t && sudo systemctl reload nginx
```

## 접근 제어

뷰어 자체에는 로그인이 없다. 아무나 소스를 올리고 남이 올린 명세서를 볼 수
있으므로 nginx basic auth 로 막는다.

```bash
sudo openssl passwd -apr1                      # 비밀번호 입력 → 해시 출력
echo '사용자명:<해시>' | sudo tee -a /etc/nginx/.llmwiki-htpasswd
sudo chown root:www-data /etc/nginx/.llmwiki-htpasswd
sudo chmod 640 /etc/nginx/.llmwiki-htpasswd
sudo systemctl reload nginx
```

**⚠ HTTPS 가 아니면 basic auth 자격증명도 평문으로 오간다.** 같은 망에서
도청하면 그대로 보이므로, 443 을 쓸 수 있는 환경이면 반드시 HTTPS 전용으로
돌린다 (`rag-ai-gov.conf` 의 '### HTTPS 전용 전환' 주석 참고). 평문으로
운영해야 한다면 그 사실을 알고 쓰는 사람에게만 계정을 주고, 다른 곳에서 쓰는
비밀번호를 재사용하지 않는다.

`auth_basic` 은 location 사이에 상속되지 않는다. `llmwiki-site.conf` 의 프록시
location 이 두 개(`/` 와 업로드 전용)이므로 **양쪽 모두**에 적혀 있어야 한다.
하나라도 빠지면 그 경로만 무인증으로 열린다.

도메인이 생겼으니 443 만 열리면 Let's Encrypt 로 바로 전환할 수 있다
(`/.well-known/acme-challenge/` 는 인증에서 빼 두었다).

## 규제 지식그래프 (`/wiki/api/reg/…`)

같은 서비스·같은 basic auth 안에서 돈다. 별도 포트도 별도 유닛도 없다.

```bash
# 데모 데이터 (한 번만 — 저널이 append-only 라 두 번 넣으면 이력이 겹친다)
sudo -u llmwiki HOME=/opt/llmwiki /opt/llmwiki/.venv/bin/llmwiki reg seed \
     -c /opt/llmwiki/config.yaml

# 판정 · 검증 · 골드셋 (LLM 을 부르지 않는다)
sudo -u llmwiki HOME=/opt/llmwiki /opt/llmwiki/.venv/bin/llmwiki reg assess \
     -c /opt/llmwiki/config.yaml

# 조문 → 의무 추출 제안 (Grok). 키는 EnvironmentFile 에만 있으므로 넘겨 준다.
sudo -u llmwiki env $(sudo cat /etc/llmwiki/llmwiki.env | grep ^XAI_) HOME=/opt/llmwiki \
     /opt/llmwiki/.venv/bin/llmwiki reg propose --llm -c /opt/llmwiki/config.yaml

# 문서·작업물 (docx·xlsx·pdf)
L="sudo -u llmwiki HOME=/opt/llmwiki /opt/llmwiki/.venv/bin/llmwiki reg"
$L ingest 규정.docx --uuid reg-x --name "AI 거버넌스 규정" --issuer 소관부서
$L template HI-19 별첨01.docx          # 서식 → 필수 절 (구성 검토 절차)
$L submit 작업물.docx --uuid evd-001 --signed --control HI-19 --service svc-001
$L consistency                          # 문서 간 값 불일치
$L link 작업물.docx --service svc-001   # 사내 sLM 이 증적 연결 제안
```

- **사내 sLM 은 서버 안에서만 열려 있다** (`127.0.0.1:11434`). 바깥에서 붙지 않으므로
  `reg link` 같은 sLM 명령은 서버에서 실행해야 한다. 망분리 관점에서는 이게 맞는 구성이다.
  모델은 `hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:Q4_K_M` 이고 A30 24GB 중
  ~19GB 를 쓴다. rag-api 와 공유하므로 동시 부하를 피할 것.
- 문서 명령은 CLI 전용이다. 파일 업로드를 API 로 열면 인증·크기·경로 문제가 따라오는데,
  지금 뷰어에는 규제용 업로드 화면이 없으므로 열지 않았다.

- **`/opt/llmwiki/compliance` 는 산출물이 아니라 감사 추적이다.** append-only
  저널이라 지우면 과거 판정의 근거가 사라진다. `docs/`·`projects/` 와 달리
  재생성할 수 없으므로 **백업 대상**이다.
- **판정은 LLM 을 호출하지 않는다.** `reg assess` 는 그래프 조회만 하므로 GPU 도
  Grok 크레딧도 쓰지 않는다. Grok 을 쓰는 것은 `reg propose --llm` 하나뿐이고,
  그 결과는 승인 그래프가 아니라 결재 큐로 간다.
- **쓰기 경로는 둘뿐이다** — 커밋 결재(`/changes/{id}/approve`)와 확정
  서명(`/assess/{uuid}/confirm`). 노드를 직접 만들거나 지우는 API 는 없다.
- 뷰어에서는 `/wiki/reg` 다. 좌측 하단 **규제 준수 평가 열기 →** 로 들어간다.
  판정·커버리지 갭·커밋 결재·그래프 네 탭이며, 화면에서 승인과 확정 서명을 할 수 있다.
  **프론트를 고쳤으면 `VITE_BASE=/wiki/` 로 다시 빌드해 올려야 한다** — 이 값이
  nginx 의 경로 접두어와 어긋나면 자산을 404 로 받아 화면이 하얗게 뜬다.

## 운영

```bash
sudo systemctl status llmwiki
sudo journalctl -u llmwiki -f
sudo tail -f /var/log/nginx/rag-ai-gov.{access,error}.log
```

- **워커는 1개 고정.** 파싱·생성 작업 상태(jobs)와 업로드 세션이 프로세스
  메모리에 있어, 늘리면 진행률 폴링이 엉뚱한 워커로 가 작업을 잃는다.
- **GPU 는 rag-api 와 공유한다.** A30 24GB 중 ~19GB 를 같은 모델이 쓰고 있어
  `llm.ollama.concurrency` 는 1 로 둔다. 대량 생성은 Grok 쪽이 빠르다.
- **경로 제한.** `server.browse_roots` 밖은 열람도 프로젝트 등록도 막힌다.
  업로드는 `server.upload_dir` 안에만 풀린다. 공개 서비스이므로 이 두 값을
  넓히지 말 것.
