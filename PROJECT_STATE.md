# Project State

## Status
Core implementation completed and locally smoke-tested.

## Objective
Provide a Telegram-controlled bridge for local Codex CLI work with:
- voice/text ingestion;
- OpenAI speech-to-text only for transcription;
- SQLite-backed job orchestration;
- multi-project context management;
- concise Telegram UX;
- background execution and service-style operation.

## Current Decisions
- New dedicated service directory: `/home/user/codex-telegram-bridge`.
- SQLite chosen over Redis for durability and minimal infrastructure.
- Separate bot and worker processes sharing a single runtime database.
- Project memory files will live inside the bridge runtime, not inside user repositories.

## Implemented
- Async Telegram ingress with allowlist and command set.
- Voice-to-text path via OpenAI transcription API.
- Durable local queue with `queued`, `running`, `done`, `failed`, `canceled`.
- Project scan/index/selection plus per-chat active project state.
- Codex CLI runner with strict `FINAL_REPORT` contract and fallback summarization.
- Runtime artifacts for logs, reports, transcripts, voice files, and job directories.
- Bootstrap and service scripts for long-running background operation.

## Verified
- `bash scripts/bootstrap.sh`
- `pytest -q`
- `python -m compileall src`
- Live `codex exec` smoke-test through the runner path

## Remaining User Input
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_API_KEY`
- `TELEGRAM_ALLOWED_USER_IDS` or `TELEGRAM_ALLOWED_CHAT_IDS`
