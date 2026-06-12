from __future__ import annotations

import argparse
from pathlib import Path

from codex_telegram_bridge.config import Settings
from codex_telegram_bridge.projects import ProjectIndexer
from codex_telegram_bridge.store import BridgeStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Codex Telegram bridge admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    sub.add_parser("reindex")
    sub.add_parser("list-projects")
    args = parser.parse_args()

    settings = Settings.load()
    store = BridgeStore(settings.paths.db)
    store.init_db()
    indexer = ProjectIndexer(store, settings.paths.project_states, settings.scan_roots)

    if args.command == "init-db":
        print(settings.paths.db)
        return
    if args.command == "reindex":
        projects = indexer.reindex()
        print(f"Indexed {len(projects)} projects")
        return
    if args.command == "list-projects":
        for project in store.list_projects():
            print(f"{project.key}\t{project.root_path}")
