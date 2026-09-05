#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# gpu-server 초기 구축 — 서버에서 1회 실행한다 (sudo 필요).
#
#   대상: Ubuntu 24.04 · NVIDIA A30 24GB · LLMWiki + 사내 sLLM(Ollama)
#
# 두 번 돌려도 안전하게 짰다. 실패하면 그 자리에서 멈춘다 — 반쯤 올라간 상태로
# 넘어가면 나중에 무엇이 됐는지 알 수 없다.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SLLM_MODEL="${SLLM_MODEL:-hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:Q4_K_M}"
APP_DIR=/opt/llmwiki
UP_DIR=/tmp/up

say(){ printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }

# ── 0. 전제 확인 ────────────────────────────────────────────────────────────
say "전제 확인"
[ -d "$UP_DIR/llmwiki" ] || { echo "코드가 없다: $UP_DIR/llmwiki — 먼저 push.sh 를 돌려라"; exit 1; }
[ -d "$UP_DIR/dist" ]    || { echo "프론트 빌드가 없다: $UP_DIR/dist — push.sh 가 web/dist 를 올린다"; exit 1; }

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
else
  cat <<'MSG'
⚠ nvidia-smi 가 없다. GPU 드라이버부터 깔아야 sLLM 이 CPU 로 떨어진다.
    sudo apt update && sudo ubuntu-drivers install
    sudo reboot
  재부팅 뒤 이 스크립트를 다시 돌려라.
MSG
  exit 1
fi

# ── 1. 패키지 ───────────────────────────────────────────────────────────────
say "패키지 설치"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-dev build-essential nginx apache2-utils rsync curl

# ── 2. 계정과 디렉터리 ──────────────────────────────────────────────────────
say "서비스 계정과 디렉터리"
id llmwiki >/dev/null 2>&1 || sudo useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin llmwiki
sudo mkdir -p "$APP_DIR"/{docs,projects,uploads,sources,compliance,knowledge,wiki,web} /etc/llmwiki
sudo chown -R llmwiki:llmwiki "$APP_DIR"

# ── 3. 코드 배치 ────────────────────────────────────────────────────────────
say "코드 배치"
sudo rsync -a --delete "$UP_DIR/llmwiki/" "$APP_DIR/llmwiki/"
sudo rsync -a --delete "$UP_DIR/dist/"    "$APP_DIR/web/dist/"
sudo cp "$UP_DIR/pyproject.toml" "$APP_DIR/pyproject.toml"
[ -d "$UP_DIR/sample" ] && sudo rsync -a "$UP_DIR/sample/" "$APP_DIR/sample/" || true
sudo chown -R llmwiki:llmwiki "$APP_DIR"

# ── 4. 파이썬 환경 ──────────────────────────────────────────────────────────
say "파이썬 환경"
[ -x "$APP_DIR/.venv/bin/python" ] || sudo -u llmwiki python3 -m venv "$APP_DIR/.venv"
sudo -u llmwiki "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
cd "$APP_DIR" && sudo -u llmwiki "$APP_DIR/.venv/bin/pip" install -q -e .

# ── 5. 설정과 키 ────────────────────────────────────────────────────────────
say "설정"
sudo cp "$UP_DIR/deploy/gpu-server/config.gpu.yaml" "$APP_DIR/config.yaml"
sudo chown llmwiki:llmwiki "$APP_DIR/config.yaml"

if [ ! -f /etc/llmwiki/llmwiki.env ]; then
  # 키는 이 스크립트가 아니라 환경변수로 받는다 — 명령 이력에 남지 않게 하려면
  #   read -rs XAI_API_KEY; export XAI_API_KEY
  # 로 먼저 넣고 스크립트를 돌린다.
  sudo tee /etc/llmwiki/llmwiki.env >/dev/null <<ENV
XAI_API_KEY=${XAI_API_KEY:-}
XAI_MODEL=${XAI_MODEL:-grok-4.20-0309-non-reasoning}
ENV
  sudo chown root:llmwiki /etc/llmwiki/llmwiki.env
  sudo chmod 640 /etc/llmwiki/llmwiki.env
  [ -n "${XAI_API_KEY:-}" ] || echo "⚠ XAI_API_KEY 가 비어 있다 — /etc/llmwiki/llmwiki.env 를 채운 뒤 재시작할 것"
else
  echo "  /etc/llmwiki/llmwiki.env 는 이미 있다 (건드리지 않음)"
fi

# ── 6. sLLM (Ollama) ────────────────────────────────────────────────────────
say "사내 sLLM — Ollama"
command -v ollama >/dev/null 2>&1 || curl -fsSL https://ollama.com/install.sh | sh

# 루프백에만 연다. 공인 IP 로 11434 가 열리면 모델이 그대로 공개된다.
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'OV'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
# 모델을 메모리에 붙들어 둔다. 짧으면 호출마다 재적재라 체감이 수십 배 느려진다.
Environment="OLLAMA_KEEP_ALIVE=30m"
# A30 24GB 한 장이므로 동시 적재는 1개로 못박는다.
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
OV
sudo systemctl daemon-reload
sudo systemctl enable --now ollama
sleep 3

say "모델 내려받기 (18GB 안팎 — 처음이면 오래 걸린다)"
ollama pull "$SLLM_MODEL"

# ── 7. LLMWiki 서비스 ───────────────────────────────────────────────────────
say "LLMWiki 서비스"
sudo cp "$UP_DIR/deploy/gpu-server/llmwiki.service" /etc/systemd/system/llmwiki.service
sudo systemctl daemon-reload
sudo systemctl enable --now llmwiki
sleep 3
sudo systemctl --no-pager --lines=15 status llmwiki || true

# ── 8. nginx ────────────────────────────────────────────────────────────────
say "nginx"
if [ ! -f /etc/nginx/.llmwiki-htpasswd ]; then
  echo "  기본 계정 llmwiki 를 만든다. 비밀번호를 입력하라:"
  sudo htpasswd -c /etc/nginx/.llmwiki-htpasswd llmwiki
fi
sudo cp "$UP_DIR/deploy/gpu-server/nginx-llmwiki.conf" /etc/nginx/sites-available/llmwiki.conf
sudo ln -sfn /etc/nginx/sites-available/llmwiki.conf /etc/nginx/sites-enabled/llmwiki.conf
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

say "완료"
cat <<'DONE'

  로컬 확인   curl -u llmwiki:<비밀번호> http://127.0.0.1/api/meta
  sLLM 확인   curl -s http://127.0.0.1:11434/api/tags | head -c 300
  로그        journalctl -u llmwiki -f
              journalctl -u ollama -f

  바깥에서 80 이 막혀 있으면 맥에서 터널로 본다:
      ssh -i <키> -L 8722:127.0.0.1:8722 ubuntu@210.206.73.80
      → http://127.0.0.1:8722
DONE
