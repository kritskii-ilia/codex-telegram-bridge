#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
ENV_FILE="${CODEX_TELEGRAM_ENV_FILE:-/home/user/codex-telegram.env}"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'

if [[ ! -f "$ENV_FILE" && -f .env.example ]]; then
  cp .env.example "$ENV_FILE"
fi

export CODEX_TELEGRAM_ENV_FILE="$ENV_FILE"

.venv/bin/codex-telegram-bridge-admin init-db >/dev/null
.venv/bin/codex-telegram-bridge-admin reindex || true

echo "Bootstrap complete. Fill $ENV_FILE and run scripts/run_bot.sh and scripts/run_worker.sh"
