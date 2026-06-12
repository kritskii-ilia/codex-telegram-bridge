#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_DIR="/etc/systemd/system"

install -m 0644 "$ROOT_DIR/systemd/codex-telegram-bridge-bot.service" "$SERVICE_DIR/"
install -m 0644 "$ROOT_DIR/systemd/codex-telegram-bridge-worker.service" "$SERVICE_DIR/"

systemctl daemon-reload
systemctl enable codex-telegram-bridge-bot.service
systemctl enable codex-telegram-bridge-worker.service

echo "Installed systemd units. Use systemctl start codex-telegram-bridge-{bot,worker}"
