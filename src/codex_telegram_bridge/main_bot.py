from __future__ import annotations

from codex_telegram_bridge.bot import TelegramBridgeBot
from codex_telegram_bridge.config import Settings
from codex_telegram_bridge.logging_utils import configure_logging
from codex_telegram_bridge.projects import ProjectIndexer
from codex_telegram_bridge.store import BridgeStore


def main() -> None:
    settings = Settings.load()
    configure_logging(settings.paths.logs, settings.log_level, "bot.log")
    store = BridgeStore(settings.paths.db)
    store.init_db()
    indexer = ProjectIndexer(store, settings.paths.project_states, settings.scan_roots)
    indexer.ensure_index()
    app = TelegramBridgeBot(settings, store, indexer).build_application()
    app.run_polling(allowed_updates=["message"])
