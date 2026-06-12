# Codex Telegram Bridge Implementation Plan

## Goal
Build a local bridge service that accepts Telegram voice/text tasks, uses OpenAI speech-to-text only for transcription, queues tasks in SQLite, runs the actual work through local Codex CLI, and returns only a structured final report back to Telegram.

## Architecture
1. `python-telegram-bot` async bot process for Telegram ingress and command handling.
2. SQLite-backed queue and metadata store for jobs, project context, chat state, transcripts, and artifacts.
3. Background worker process polling SQLite, launching Codex CLI, enforcing timeout/cancel semantics, and persisting results.
4. Project indexer that scans configured WSL roots, resolves projects by name/path/alias, and stores service-owned state summaries.
5. Runtime home under `runtime/` for logs, database, voice artifacts, job artifacts, and project memory.

## Main Components
- `config.py`: env parsing and runtime path setup.
- `store.py`: durable SQLite job/project store.
- `projects.py`: filesystem project discovery and summary building.
- `speech.py`: Telegram voice download preparation and OpenAI transcription.
- `intents.py`: lightweight local parsing for project switching and status-like commands.
- `runner.py`: Codex prompt wrapping, subprocess execution, timeout/cancel handling, final report extraction.
- `bot.py`: Telegram commands, allowlist, task ingestion, and concise replies.
- `worker.py`: queue polling, status transitions, report dispatch, project-memory updates.

## Delivery Stages
1. Project skeleton plus planning/state docs.
2. Core config, database schema, artifacts layout, and project index.
3. Telegram bot and speech-to-text flow.
4. Codex runner and worker orchestration.
5. Bootstrap/install/run scripts, systemd units, README.
6. Smoke tests and state document updates.
