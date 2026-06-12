from __future__ import annotations

import asyncio
import html
import logging
import re
from contextlib import suppress
from pathlib import Path

from telegram.constants import ParseMode
from telegram import Bot

from codex_telegram_bridge.config import Settings
from codex_telegram_bridge.projects import ProjectIndexer
from codex_telegram_bridge.reporting import extract_final_report_meta, format_report_for_telegram, save_text
from codex_telegram_bridge.runner import CodexRunner
from codex_telegram_bridge.speech import TextToSpeechService
from codex_telegram_bridge.store import BridgeStore
from codex_telegram_bridge.models import utc_now


LOGGER = logging.getLogger(__name__)


class WorkerService:
    def __init__(self, settings: Settings, store: BridgeStore, project_indexer: ProjectIndexer) -> None:
        self.settings = settings
        self.store = store
        self.project_indexer = project_indexer
        self.runner = CodexRunner(settings, store, project_indexer)
        self.bot = Bot(settings.telegram_bot_token) if settings.telegram_bot_token else None
        self.tts = TextToSpeechService(settings) if settings.openai_api_key else None

    async def run_forever(self) -> None:
        while True:
            job = self.store.claim_next_job()
            if not job:
                await asyncio.sleep(self.settings.worker_poll_interval_seconds)
                continue
            await self._process_job(job)

    async def _process_job(self, job) -> None:
        project_key = job.project_key or self.store.get_active_project(job.chat_id)
        if not project_key:
            inferred = self.project_indexer.resolve_project_hint(job.prompt_text)
            project_key = inferred.key if inferred else None
        if not project_key and self.settings.default_project_hint:
            default_project = self.store.find_project(self.settings.default_project_hint)
            if not default_project:
                self.project_indexer.reindex()
                default_project = self.store.find_project(self.settings.default_project_hint)
            project_key = default_project.key if default_project else None
        project = self.store.find_project(project_key) if project_key else None
        if project:
            self.store.set_active_project(job.chat_id, job.user_id, project.key)

        progress_task = asyncio.create_task(self._notify_long_task(job))
        result = await self.runner.run_job(job, project)
        progress_task.cancel()
        with suppress(asyncio.CancelledError):
            await progress_task
        report_path = self.settings.paths.reports / f"job-{job.id}.txt"
        save_text(report_path, result.final_report)
        meta = extract_final_report_meta(result.final_report)
        update_fields = {
            "status": result.status,
            "completed_at": utc_now(),
            "exit_code": result.exit_code,
            "final_report_path": str(report_path),
            "failure_reason": None if result.status == "done" else f"Job finished with status {result.status}",
            "codex_pid": None,
        }
        self.store.update_job_fields(job.id, **update_fields)
        chat_updates = {"last_final_report_path": str(report_path)}
        if meta.memory_table:
            chat_updates["last_table_name"] = meta.memory_table
        if meta.memory_sheet:
            chat_updates["last_sheet_name"] = meta.memory_sheet
        self.store.update_chat_state(job.chat_id, job.user_id, **chat_updates)
        if meta.action_required in {"clarify", "confirm"} and meta.question and meta.resume_prompt:
            self.store.set_pending_action(
                job.chat_id,
                job.user_id,
                kind=meta.action_required,
                question=meta.question,
                resume_prompt=meta.resume_prompt,
            )
            if self.bot:
                await self.bot.send_message(chat_id=job.chat_id, text=meta.question)
                await self._send_voice_reply_if_needed(job, meta.question)
            LOGGER.info("Job produced pending action", extra={"job_id": job.id, "kind": meta.action_required})
            return

        self.store.clear_pending_action(job.chat_id, job.user_id)
        if project and result.status == "done":
            self.project_indexer.update_project_memory(project, result.final_report)
        if self.bot:
            chat_state = self.store.get_chat_state(job.chat_id)
            response_mode = chat_state.response_mode if chat_state else "brief"
            prefix = {
                "done": "Готово",
                "failed": "Не получилось",
                "canceled": "Остановлено",
            }.get(result.status, "Готово")
            rendered_messages = format_report_for_telegram(prefix, result.final_report, mode=response_mode)
            for message in rendered_messages:
                await self.bot.send_message(
                    chat_id=job.chat_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            await self._send_attachments(job, meta.attachments)
            await self._send_voice_reply_if_needed(job, self._plain_text("\n\n".join(rendered_messages)))
        LOGGER.info("Job processed", extra={"job_id": job.id, "project_key": project.key if project else None})

    async def _notify_long_task(self, job) -> None:
        if not self.bot or self.settings.long_task_progress_seconds <= 0:
            return
        try:
            await asyncio.sleep(self.settings.long_task_progress_seconds)
            current = self.store.get_job(job.id)
            if current and current.status == "running":
                await self.bot.send_message(chat_id=job.chat_id, text="Работаю, задача ещё выполняется.")
        except asyncio.CancelledError:
            return

    async def _send_attachments(self, job, attachments: list[str]) -> None:
        if not self.bot or not attachments:
            return
        base_dir = Path(job.artifact_dir or "")
        for raw_path in attachments:
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = (base_dir / candidate).resolve()
            if not candidate.exists() or not candidate.is_file():
                continue
            suffix = candidate.suffix.lower()
            with candidate.open("rb") as handle:
                if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                    await self.bot.send_photo(chat_id=job.chat_id, photo=handle)
                else:
                    await self.bot.send_document(chat_id=job.chat_id, document=handle)

    async def _send_voice_reply_if_needed(self, job, text: str) -> None:
        if not self.bot or not self.tts:
            return
        chat_state = self.store.get_chat_state(job.chat_id)
        if not chat_state or not chat_state.voice_replies_enabled:
            return
        clipped = text.strip()
        if not clipped:
            return
        clipped = clipped[:1500]
        voice_path = self.settings.paths.reports / f"job-{job.id}.ogg"
        try:
            self.tts.synthesize(clipped, voice_path)
        except Exception:
            LOGGER.exception("Voice synthesis failed", extra={"job_id": job.id})
            return
        with voice_path.open("rb") as handle:
            try:
                await self.bot.send_voice(chat_id=job.chat_id, voice=handle)
            except Exception:
                LOGGER.exception("Voice upload failed", extra={"job_id": job.id})

    def _plain_text(self, text: str) -> str:
        unescaped = html.unescape(re.sub(r"<br>", "\n", re.sub(r"<[^>]+>", "", text)))
        return re.sub(r"\n{3,}", "\n\n", unescaped).strip()
