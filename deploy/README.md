# 배포

운영 서버에 올라가 있는 구성 그대로다. 여기 파일들은 서버에 있는 것을 그대로
가져온 것이므로, 서버를 고쳤으면 여기도 같이 고쳐야 한다.

서비스 주소: `http://<서버>/wiki/` — 실제 호스트와 계정은 저장소에 적지 않는다
(공개 저장소다). 사내 위키나 운영 문서를 볼 것.

## 구성

```
브라우저 ──80──▶ nginx ──┬─▶ /            rag-ai-gov (기존 서비스, 그대로 둔다)
                         └─▶ /wiki/       llmwiki  127.0.0.1:8722
```

`/wiki/` 하위 경로로 붙인 것은, 80 을 기존 서비스가 `default_server` 로 잡고
있고 443·별도 포트가 상위망에서 열리지 않는 환경이기 때문이다. 접두어를 바꾸려면
프론트를 같은 값으로 다시 빌드해야 한다 (`VITE_BASE`).

| 파일 | 배치 위치 |
|---|---|
| `nginx/llmwiki-app.conf` | `/etc/nginx/snippets/llmwiki-app.conf` |
| `systemd/llmwiki.service` | `/etc/systemd/system/llmwiki.service` |
| `config.server.yaml` | `/opt/llmwiki/config.yaml` |
| `llmwiki.env.example` | `/etc/llmwiki/llmwiki.env` (키를 채워서) |

## 설치

```bash
# 1) 서비스 계정과 디렉터리
sudo useradd --system --home-dir /opt/llmwiki --shell /usr/sbin/nologin llmwiki
sudo mkdir -p /opt/llmwiki/{docs,projects,uploads,sources} /etc/llmwiki
sudo chown -R llmwiki:llmwiki /opt/llmwiki

# 2) 코드 (web/dist 는 로컬에서 빌드해 올린다 — 서버에 node 가 없다)
#    VITE_BASE 는 nginx 의 경로 접두어와 반드시 같아야 한다.
cd web && VITE_BASE=/wiki/ npm run build && cd ..
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

# 6) nginx — 기존 앱 설정에서 include 한다 (80·443 양쪽에 함께 적용된다)
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

`auth_basic` 은 location 사이에 상속되지 않는다. `llmwiki-app.conf` 안의
프록시 location 이 두 개이므로 **양쪽 모두**에 적혀 있어야 한다. 하나라도
빠지면 그 경로만 무인증으로 열린다.

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
