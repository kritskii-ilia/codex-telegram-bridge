from __future__ import annotations

import asyncio

from codex_telegram_bridge.config import Settings
from codex_telegram_bridge.logging_utils import configure_logging
from codex_telegram_bridge.projects import ProjectIndexer
from codex_telegram_bridge.store import BridgeStore
from codex_telegram_bridge.worker import WorkerService


def main() -> None:
    settings = Settings.load()
    configure_logging(settings.paths.logs, settings.log_level, "worker.log")
    store = BridgeStore(settings.paths.db)
    store.init_db()
    indexer = ProjectIndexer(store, settings.paths.project_states, settings.scan_roots)
    indexer.ensure_index()
    asyncio.run(WorkerService(settings, store, indexer).run_forever())
