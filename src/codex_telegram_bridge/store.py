from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from codex_telegram_bridge.models import ChatStateRecord, JobRecord, ProjectRecord, utc_now


class BridgeStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    status TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    project_key TEXT,
                    requested_project TEXT,
                    prompt_text TEXT NOT NULL,
                    transcript_text TEXT,
                    voice_file_path TEXT,
                    transcript_file_path TEXT,
                    image_file_paths TEXT,
                    final_report_path TEXT,
                    log_path TEXT,
                    artifact_dir TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    failure_reason TEXT,
                    exit_code INTEGER,
                    codex_pid INTEGER
                );

                CREATE TABLE IF NOT EXISTS chat_state (
                    chat_id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    active_project_key TEXT,
                    response_mode TEXT NOT NULL DEFAULT 'brief',
                    voice_replies_enabled INTEGER NOT NULL DEFAULT 0,
                    last_table_name TEXT,
                    last_sheet_name TEXT,
                    last_final_report_path TEXT,
                    pending_action_kind TEXT,
                    pending_action_question TEXT,
                    pending_action_resume_prompt TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    key TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    root_path TEXT NOT NULL UNIQUE,
                    markers TEXT NOT NULL,
                    aliases TEXT NOT NULL,
                    last_scanned_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()}
            if "image_file_paths" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN image_file_paths TEXT")
            chat_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_state)").fetchall()}
            migrations = {
                "response_mode": "ALTER TABLE chat_state ADD COLUMN response_mode TEXT NOT NULL DEFAULT 'brief'",
                "voice_replies_enabled": "ALTER TABLE chat_state ADD COLUMN voice_replies_enabled INTEGER NOT NULL DEFAULT 0",
                "last_table_name": "ALTER TABLE chat_state ADD COLUMN last_table_name TEXT",
                "last_sheet_name": "ALTER TABLE chat_state ADD COLUMN last_sheet_name TEXT",
                "last_final_report_path": "ALTER TABLE chat_state ADD COLUMN last_final_report_path TEXT",
                "pending_action_kind": "ALTER TABLE chat_state ADD COLUMN pending_action_kind TEXT",
                "pending_action_question": "ALTER TABLE chat_state ADD COLUMN pending_action_question TEXT",
                "pending_action_resume_prompt": "ALTER TABLE chat_state ADD COLUMN pending_action_resume_prompt TEXT",
            }
            for name, statement in migrations.items():
                if name not in chat_columns:
                    try:
                        conn.execute(statement)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise

    def create_job(
        self,
        *,
        source_type: str,
        chat_id: int,
        user_id: int,
        project_key: str | None,
        requested_project: str | None,
        prompt_text: str,
        transcript_text: str | None = None,
        voice_file_path: str | None = None,
        transcript_file_path: str | None = None,
        image_file_paths: str | None = None,
        artifact_dir: str | None = None,
        log_path: str | None = None,
    ) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO jobs (
                    status, source_type, chat_id, user_id, project_key, requested_project,
                    prompt_text, transcript_text, voice_file_path, transcript_file_path,
                    image_file_paths, artifact_dir, log_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "queued",
                    source_type,
                    chat_id,
                    user_id,
                    project_key,
                    requested_project,
                    prompt_text,
                    transcript_text,
                    voice_file_path,
                    transcript_file_path,
                    image_file_paths,
                    artifact_dir,
                    log_path,
                    utc_now(),
                ),
            )
            return int(cursor.lastrowid)

    def set_active_project(self, chat_id: int, user_id: int, project_key: str | None) -> None:
        self._ensure_chat_state(chat_id, user_id)
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE chat_state
                SET user_id = ?, active_project_key = ?, updated_at = ?
                WHERE chat_id = ?
                """,
                (user_id, project_key, utc_now(), chat_id),
            )

    def get_active_project(self, chat_id: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT active_project_key FROM chat_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            return row["active_project_key"] if row else None

    def get_chat_state(self, chat_id: int) -> ChatStateRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT chat_id, user_id, active_project_key, response_mode, voice_replies_enabled,
                       last_table_name, last_sheet_name, last_final_report_path,
                       pending_action_kind, pending_action_question, pending_action_resume_prompt, updated_at
                FROM chat_state
                WHERE chat_id = ?
                """,
                (chat_id,),
            ).fetchone()
        return ChatStateRecord(**dict(row)) if row else None

    def update_chat_state(self, chat_id: int, user_id: int, **fields: object) -> None:
        self._ensure_chat_state(chat_id, user_id)
        payload = {"user_id": user_id, "updated_at": utc_now(), **fields}
        columns = ", ".join(f"{key} = ?" for key in payload)
        values = list(payload.values()) + [chat_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE chat_state SET {columns} WHERE chat_id = ?", values)

    def set_pending_action(self, chat_id: int, user_id: int, *, kind: str, question: str, resume_prompt: str) -> None:
        self.update_chat_state(
            chat_id,
            user_id,
            pending_action_kind=kind,
            pending_action_question=question,
            pending_action_resume_prompt=resume_prompt,
        )

    def clear_pending_action(self, chat_id: int, user_id: int) -> None:
        self.update_chat_state(
            chat_id,
            user_id,
            pending_action_kind=None,
            pending_action_question=None,
            pending_action_resume_prompt=None,
        )

    def upsert_project(self, record: ProjectRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO projects (key, name, root_path, markers, aliases, last_scanned_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    name=excluded.name,
                    root_path=excluded.root_path,
                    markers=excluded.markers,
                    aliases=excluded.aliases,
                    last_scanned_at=excluded.last_scanned_at
                """,
                (
                    record.key,
                    record.name,
                    record.root_path,
                    record.markers,
                    record.aliases,
                    record.last_scanned_at,
                ),
            )

    def list_projects(self) -> list[ProjectRecord]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, name, root_path, markers, aliases, last_scanned_at FROM projects ORDER BY name"
            ).fetchall()
        return [ProjectRecord(**dict(row)) for row in rows]

    def find_project(self, key_or_name: str) -> ProjectRecord | None:
        needle = key_or_name.strip().lower()
        if not needle:
            return None
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, name, root_path, markers, aliases, last_scanned_at FROM projects"
            ).fetchall()
        for row in rows:
            record = ProjectRecord(**dict(row))
            aliases = {alias.strip().lower() for alias in record.aliases.split(",") if alias.strip()}
            if needle in {record.key.lower(), record.name.lower(), record.root_path.lower(), *aliases}:
                return record
            if needle in record.name.lower() or needle in record.root_path.lower():
                return record
        return None

    def claim_next_job(self) -> JobRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'queued'
                ORDER BY id ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ? AND status = 'queued'",
                (utc_now(), row["id"]),
            )
            claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
        return JobRecord(**dict(claimed)) if claimed else None

    def update_job_fields(self, job_id: int, **fields: object) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [job_id]
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {columns} WHERE id = ?", values)

    def get_job(self, job_id: int) -> JobRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return JobRecord(**dict(row)) if row else None

    def list_jobs(self, limit: int = 20, statuses: tuple[str, ...] | None = None) -> list[JobRecord]:
        query = "SELECT * FROM jobs"
        params: list[object] = []
        if statuses:
            query += " WHERE status IN (%s)" % ",".join("?" for _ in statuses)
            params.extend(statuses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [JobRecord(**dict(row)) for row in rows]

    def get_running_job(self) -> JobRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE status = 'running' ORDER BY id ASC LIMIT 1"
            ).fetchone()
        return JobRecord(**dict(row)) if row else None

    def request_cancel(self, job_id: int) -> None:
        self.update_job_fields(job_id, cancel_requested=1)

    def get_last_finished_job(self, chat_id: int) -> JobRecord | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE chat_id = ? AND status IN ('done', 'failed', 'canceled')
                ORDER BY id DESC
                LIMIT 1
                """,
                (chat_id,),
            ).fetchone()
        return JobRecord(**dict(row)) if row else None

    def _ensure_chat_state(self, chat_id: int, user_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_state (chat_id, user_id, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(chat_id) DO NOTHING
                """,
                (chat_id, user_id, utc_now()),
            )
