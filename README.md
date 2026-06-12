# Codex Telegram Bridge

Мост для управления локальным Codex CLI через Telegram. Отправляй задачи текстом или голосом — бот выполнит их локально и вернёт отчёт.

## Features

- Текстовые и голосовые сообщения (транскрипция через OpenAI)
- Очередь задач с асинхронным выполнением
- Контроль доступа по Telegram user ID
- Отслеживание проектов и контекста между задачами
- Структурированные отчёты о выполнении
- Автономный воркер (бот и воркер работают отдельно)

## Tech Stack

- Python 3.12
- Telegram Bot API
- OpenAI API (speech-to-text)
- SQLite
- systemd

## Quick Start

```bash
bash scripts/bootstrap.sh
# Заполни токены в .env
sudo bash scripts/run_bot.sh
sudo bash scripts/run_worker.sh
```

## Commands

`/start` `/help` `/status` `/queue` `/current` `/last` `/cancel` `/projects` `/use_project <name>`
