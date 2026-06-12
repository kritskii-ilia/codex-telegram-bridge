from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from codex_telegram_bridge.paths import RuntimePaths


def _parse_int_set(raw: str | None) -> set[int]:
    if not raw:
        return set()
    result: set[int] = set()
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        result.add(int(value))
    return result


def _merge_int_sets(*raw_values: str | None) -> set[int]:
    merged: set[int] = set()
    for raw in raw_values:
        merged.update(_parse_int_set(raw))
    return merged


def _parse_paths(raw: str | None, default: list[str]) -> list[Path]:
    values = raw.split(",") if raw else default
    return [Path(item.strip()).expanduser().resolve() for item in values if item.strip()]


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openai_api_key: str
    openai_transcribe_model: str
    allowed_user_ids: set[int]
    allowed_chat_ids: set[int]
    bridge_home: Path
    scan_roots: list[Path]
    default_project_root: Path
    default_project_hint: str | None
    downloads_path: Path | None
    codex_bin: str
    codex_model: str | None
    codex_run_as_root: bool
    codex_sandbox: str
    codex_approval_policy: str
    job_timeout_seconds: int
    worker_poll_interval_seconds: float
    long_task_progress_seconds: float
    image_collect_window_seconds: float
    log_level: str
    telegram_status_notifications: bool
    openai_tts_model: str
    openai_tts_voice: str
    paths: RuntimePaths

    @classmethod
    def load(cls, env_file: str | None = None) -> "Settings":
        env_candidates: list[str] = []
        if env_file:
            env_candidates.append(env_file)
        env_from_os = os.environ.get("CODEX_TELEGRAM_ENV_FILE", "").strip()
        if env_from_os:
            env_candidates.append(env_from_os)
        explicit_env = bool(env_candidates)
        if not explicit_env:
            env_candidates.extend(
                [
                    "/home/user/codex-telegram.env",
                    "/home/user/codex-telegram-bridge/.env",
                ]
            )
        for candidate in env_candidates:
            if candidate and Path(candidate).exists():
                load_dotenv(candidate, override=False)

        bridge_home = Path(
            os.environ.get("BRIDGE_HOME", "/var/lib/codex-telegram")
        ).expanduser().resolve()
        logs_root = Path(
            os.environ.get("LOGS_ROOT", str(bridge_home / "logs"))
        ).expanduser().resolve()
        state_db_path = Path(
            os.environ.get("STATE_DB_PATH", str(bridge_home / "bridge.sqlite3"))
        ).expanduser().resolve()
        paths = RuntimePaths.from_home(bridge_home, logs=logs_root, db=state_db_path)
        paths.ensure()

        telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        default_project_root = Path(
            os.environ.get("PROJECTS_ROOT") or os.environ.get("DEFAULT_PROJECT_ROOT", "/srv/projects")
        ).expanduser().resolve()
        downloads_raw = os.environ.get("DOWNLOADS_PATH", "").strip()
        scan_root_values = os.environ.get("BRIDGE_SCAN_ROOTS")
        default_scan_roots = [str(default_project_root), "/home/user"]
        return cls(
            telegram_bot_token=telegram_bot_token,
            openai_api_key=openai_api_key,
            openai_transcribe_model=os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe").strip(),
            allowed_user_ids=_merge_int_sets(
                os.environ.get("TELEGRAM_ALLOWED_USER_IDS"),
                os.environ.get("TELEGRAM_ALLOWED_USER_ID"),
            ),
            allowed_chat_ids=_merge_int_sets(
                os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS"),
                os.environ.get("TELEGRAM_ADMIN_CHAT_ID"),
            ),
            bridge_home=bridge_home,
            scan_roots=_parse_paths(scan_root_values, default_scan_roots),
            default_project_root=default_project_root,
            default_project_hint=os.environ.get("DEFAULT_PROJECT_HINT", "").strip() or None,
            downloads_path=Path(downloads_raw).expanduser().resolve() if downloads_raw else None,
            codex_bin=os.environ.get("CODEX_BIN", "codex").strip(),
            codex_model=os.environ.get("CODEX_MODEL", "").strip() or None,
            codex_run_as_root=_parse_bool(
                os.environ.get("CODEX_RUN_AS_ROOT", os.environ.get("RUN_AS_ROOT")),
                True,
            ),
            codex_sandbox=os.environ.get("CODEX_SANDBOX", "danger-full-access").strip(),
            codex_approval_policy=os.environ.get("CODEX_APPROVAL_POLICY", "never").strip(),
            job_timeout_seconds=int(os.environ.get("JOB_TIMEOUT_SECONDS", "5400")),
            worker_poll_interval_seconds=float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "3")),
            long_task_progress_seconds=float(os.environ.get("LONG_TASK_PROGRESS_SECONDS", "45")),
            image_collect_window_seconds=float(os.environ.get("IMAGE_COLLECT_WINDOW_SECONDS", "4")),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            telegram_status_notifications=_parse_bool(os.environ.get("TELEGRAM_STATUS_NOTIFICATIONS"), True),
            openai_tts_model=os.environ.get("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip(),
            openai_tts_voice=os.environ.get("OPENAI_TTS_VOICE", "alloy").strip(),
            paths=paths,
        )

    def validate_for_bot(self) -> None:
        if not self.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    def validate_for_transcription(self) -> None:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for speech-to-text")
