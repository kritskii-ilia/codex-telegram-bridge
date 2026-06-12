#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
source .venv/bin/activate
export CODEX_TELEGRAM_ENV_FILE="${CODEX_TELEGRAM_ENV_FILE:-/home/user/codex-telegram.env}"
exec .venv/bin/codex-telegram-bridge-worker
