from pathlib import Path

from codex_telegram_bridge.config import Settings


def test_settings_loads_external_env_and_new_variable_names(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "bridge.env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ADMIN_CHAT_ID=10001",
                "TELEGRAM_ALLOWED_USER_ID=20002",
                "OPENAI_API_KEY=test-openai",
                "OPENAI_TRANSCRIBE_MODEL=test-transcribe",
                f"BRIDGE_HOME={tmp_path / 'runtime'}",
                f"LOGS_ROOT={tmp_path / 'logs'}",
                f"STATE_DB_PATH={tmp_path / 'state' / 'bridge.sqlite3'}",
                f"PROJECTS_ROOT={tmp_path / 'projects'}",
                f"DOWNLOADS_PATH={tmp_path / 'downloads'}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CODEX_TELEGRAM_ENV_FILE", str(env_file))

    settings = Settings.load()

    assert settings.telegram_bot_token == "test-token"
    assert settings.openai_api_key == "test-openai"
    assert settings.openai_transcribe_model == "test-transcribe"
    assert settings.allowed_chat_ids == {10001}
    assert settings.allowed_user_ids == {20002}
    assert settings.default_project_root == (tmp_path / "projects").resolve()
    assert settings.downloads_path == (tmp_path / "downloads").resolve()
    assert settings.paths.logs == (tmp_path / "logs").resolve()
    assert settings.paths.db == (tmp_path / "state" / "bridge.sqlite3").resolve()
