from pathlib import Path

from codex_telegram_bridge.runner import CodexRunner
from codex_telegram_bridge.projects import ProjectIndexer
from codex_telegram_bridge.store import BridgeStore
from codex_telegram_bridge.config import Settings


def test_store_adds_image_paths_column(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path / "test.sqlite3")
    store.init_db()
    with store.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
    assert "image_file_paths" in columns


def test_runner_attaches_images_to_command(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "bridge.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                f"BRIDGE_HOME={tmp_path / 'runtime'}",
                f"PROJECTS_ROOT={tmp_path / 'projects'}",
                "CODEX_RUN_AS_ROOT=false",
                "CODEX_BIN=/usr/bin/codex",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_TELEGRAM_ENV_FILE", str(env_file))
    settings = Settings.load()
    store = BridgeStore(settings.paths.db)
    store.init_db()
    job_id = store.create_job(
        source_type="photo",
        chat_id=1,
        user_id=1,
        project_key=None,
        requested_project=None,
        prompt_text="solve from image",
        image_file_paths="/tmp/a.png,/tmp/b.jpg",
    )
    job = store.get_job(job_id)
    assert job is not None
    runner = CodexRunner(settings, store, ProjectIndexer(store, settings.paths.project_states, settings.scan_roots))
    command = runner._build_command(job=job, last_message_path=tmp_path / "last.txt", project_root=tmp_path)
    assert command.count("-i") == 2
