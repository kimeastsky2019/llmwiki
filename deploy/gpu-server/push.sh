#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# 맥에서 실행 — 프론트를 빌드해 gpu-server 로 올린다.
#
#   ./deploy/gpu-server/push.sh              코드 + 프론트 전송
#   ./deploy/gpu-server/push.sh --bootstrap  전송 후 서버에서 초기 구축까지
#
# 서버에는 node 가 없다. 빌드는 반드시 맥에서 한다.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

HOST="${HOST:-210.206.73.80}"
USER_="${SSH_USER:-ubuntu}"
KEY="${KEY:-$HOME/Documents/Webpage/ETS/dhkim-key.pem}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

[ -f "$KEY" ] || { echo "키가 없다: $KEY"; exit 1; }
chmod 600 "$KEY" 2>/dev/null || true
SSH=(ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$USER_@$HOST")
RSYNC_E="ssh -i $KEY -o StrictHostKeyChecking=accept-new"

echo "▶ 프론트 빌드"
( cd "$ROOT/web" && npm run build )

echo "▶ 전송 → $USER_@$HOST:/tmp/up"
"${SSH[@]}" 'mkdir -p /tmp/up/deploy'
rsync -az --delete -e "$RSYNC_E" \
  --exclude __pycache__ --exclude '*.pyc' --exclude '* 2.*' \
  "$ROOT/llmwiki/" "$USER_@$HOST:/tmp/up/llmwiki/"
rsync -az --delete -e "$RSYNC_E" "$ROOT/web/dist/"    "$USER_@$HOST:/tmp/up/dist/"
rsync -az --delete -e "$RSYNC_E" "$ROOT/sample/"      "$USER_@$HOST:/tmp/up/sample/"
rsync -az          -e "$RSYNC_E" "$ROOT/pyproject.toml" "$USER_@$HOST:/tmp/up/pyproject.toml"
rsync -az --delete -e "$RSYNC_E" "$ROOT/deploy/"      "$USER_@$HOST:/tmp/up/deploy/"

if [ "${1:-}" = "--bootstrap" ]; then
  echo "▶ 서버 초기 구축"
  # 키는 파일이나 명령 이력에 남기지 않고 이 실행에만 넘긴다.
  if [ -z "${XAI_API_KEY:-}" ]; then
    read -rsp "XAI_API_KEY (엔터로 건너뛰기): " XAI_API_KEY; echo
  fi
  "${SSH[@]}" "XAI_API_KEY='${XAI_API_KEY}' bash /tmp/up/deploy/gpu-server/bootstrap.sh"
else
  echo "▶ 재배포만 수행 — 서비스 재시작"
  "${SSH[@]}" 'sudo rsync -a --delete /tmp/up/llmwiki/ /opt/llmwiki/llmwiki/ &&
               sudo rsync -a --delete /tmp/up/dist/ /opt/llmwiki/web/dist/ &&
               sudo chown -R llmwiki:llmwiki /opt/llmwiki &&
               sudo systemctl restart llmwiki &&
               sleep 2 && systemctl --no-pager --lines=10 status llmwiki'
fi
echo "▶ 끝"
