from pathlib import Path

import codex_telegram_bridge.runner as runner_module

from codex_telegram_bridge.config import Settings
from codex_telegram_bridge.projects import ProjectIndexer
from codex_telegram_bridge.runner import CodexRunner
from codex_telegram_bridge.store import BridgeStore


def test_runner_prefixes_sudo_when_root_mode_enabled(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "bridge.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                f"BRIDGE_HOME={tmp_path / 'runtime'}",
                f"PROJECTS_ROOT={tmp_path / 'projects'}",
                "CODEX_RUN_AS_ROOT=true",
                "CODEX_BIN=/usr/bin/codex",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_TELEGRAM_ENV_FILE", str(env_file))
    monkeypatch.setattr(runner_module.os, "geteuid", lambda: 1000)

    settings = Settings.load()
    store = BridgeStore(settings.paths.db)
    store.init_db()
    job_id = store.create_job(
        source_type="text",
        chat_id=1,
        user_id=1,
        project_key=None,
        requested_project=None,
        prompt_text="hello",
    )
    job = store.get_job(job_id)
    assert job is not None
    runner = CodexRunner(settings, store, ProjectIndexer(store, settings.paths.project_states, settings.scan_roots))

    command = runner._build_command(job=job, last_message_path=tmp_path / "last.txt", project_root=tmp_path)

    assert command[-1] != ""
    assert "exec" in command
    assert "/usr/bin/codex" in command
