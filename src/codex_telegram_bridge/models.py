from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


JOB_STATUSES = {"queued", "running", "done", "failed", "canceled"}


@dataclass(slots=True)
class ProjectRecord:
    key: str
    name: str
    root_path: str
    markers: str
    aliases: str
    last_scanned_at: str


@dataclass(slots=True)
class JobRecord:
    id: int
    status: str
    source_type: str
    chat_id: int
    user_id: int
    project_key: str | None
    requested_project: str | None
    prompt_text: str
    transcript_text: str | None
    voice_file_path: str | None
    transcript_file_path: str | None
    image_file_paths: str | None
    final_report_path: str | None
    log_path: str | None
    artifact_dir: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    cancel_requested: int
    failure_reason: str | None
    exit_code: int | None
    codex_pid: int | None


@dataclass(slots=True)
class ChatStateRecord:
    chat_id: int
    user_id: int
    active_project_key: str | None
    response_mode: str
    voice_replies_enabled: int
    last_table_name: str | None
    last_sheet_name: str | None
    last_final_report_path: str | None
    pending_action_kind: str | None
    pending_action_question: str | None
    pending_action_resume_prompt: str | None
    updated_at: str


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
