from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telegram.error import NetworkError, TimedOut
from openai import OpenAIError
from telegram import Update
from telegram.constants import ChatAction
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from codex_telegram_bridge.config import Settings
from codex_telegram_bridge.intents import parse_local_intent
from codex_telegram_bridge.models import utc_now
from codex_telegram_bridge.projects import ProjectIndexer
from codex_telegram_bridge.reporting import format_detailed_report_for_telegram, format_report_for_telegram
from codex_telegram_bridge.speech import SpeechToTextService
from codex_telegram_bridge.store import BridgeStore


LOGGER = logging.getLogger(__name__)


class TelegramBridgeBot:
    def __init__(self, settings: Settings, store: BridgeStore, project_indexer: ProjectIndexer) -> None:
        self.settings = settings
        self.store = store
        self.project_indexer = project_indexer
        self.stt = SpeechToTextService(settings) if settings.openai_api_key else None
        self._pending_image_batches: dict[int, dict[str, object]] = {}

    def build_application(self) -> Application:
        self.settings.validate_for_bot()
        application = Application.builder().token(self.settings.telegram_bot_token).build()
        application.add_handler(CommandHandler("start", self.start))
        application.add_handler(CommandHandler("help", self.help))
        application.add_handler(CommandHandler("status", self.status))
        application.add_handler(CommandHandler("queue", self.queue))
        application.add_handler(CommandHandler("current", self.current))
        application.add_handler(CommandHandler("last", self.last))
        application.add_handler(CommandHandler("cancel", self.cancel))
        application.add_handler(CommandHandler("projects", self.projects))
        application.add_handler(CommandHandler("use_project", self.use_project))
        application.add_handler(CommandHandler("details", self.details))
        application.add_handler(CommandHandler("brief", self.brief))
        application.add_handler(CommandHandler("verbose", self.verbose))
        application.add_handler(CommandHandler("voice_on", self.voice_on))
        application.add_handler(CommandHandler("voice_off", self.voice_off))
        application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, self.handle_photo))
        application.add_handler(
            MessageHandler(filters.Document.IMAGE & ~filters.COMMAND, self.handle_image_document)
        )
        application.add_handler(MessageHandler(filters.VOICE & ~filters.COMMAND, self.handle_voice))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        return application

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._safe_reply_text(update, "Bridge активен. Отправьте голосовую или текстовую задачу.")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._safe_reply_text(
            update,
            "/status /queue /current /last /details /brief /verbose /voice_on /voice_off /cancel /projects /use_project <name_or_path>\n"
            "Обычный текст или voice -> новая задача."
        )

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        running = self.store.get_running_job()
        queued = self.store.list_jobs(limit=50, statuses=("queued",))
        project_key = self.store.get_active_project(update.effective_chat.id)
        if running:
            text = f"Текущая задача: #{running.id} ({running.status}). В очереди {len(queued)}. Активный проект: {project_key or 'не выбран'}."
        else:
            text = f"Активных задач нет. В очереди {len(queued)}. Активный проект: {project_key or 'не выбран'}."
        await self._safe_reply_text(update, text)

    async def queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        jobs = list(reversed(self.store.list_jobs(limit=10, statuses=("queued", "running"))))
        if not jobs:
            await self._safe_reply_text(update, "Очередь пуста.")
            return
        lines = [f"#{job.id} {job.status} [{job.project_key or '-'}] {job.prompt_text[:80]}" for job in jobs]
        await self._safe_reply_text(update, "\n".join(lines))

    async def current(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        project_key = self.store.get_active_project(update.effective_chat.id)
        running = self.store.get_running_job()
        text = (
            f"Активный проект: {project_key or 'не выбран'}\nТекущая задача: #{running.id} {running.status}"
            if running
            else f"Активный проект: {project_key or 'не выбран'}\nТекущей задачи нет."
        )
        await self._safe_reply_text(update, text)

    async def last(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        job = self.store.get_last_finished_job(update.effective_chat.id)
        if not job:
            await self._safe_reply_text(update, "История пока пуста.")
            return
        report = Path(job.final_report_path).read_text(encoding="utf-8") if job.final_report_path and Path(job.final_report_path).exists() else "Финальный отчёт не найден."
        status_text = self._status_text(job.status, prefix="Последний ответ")
        for message in format_report_for_telegram(status_text, report):
            await update.message.reply_text(
                message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

    async def details(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        await self._send_last_details(update)

    async def brief(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        self.store.update_chat_state(update.effective_chat.id, update.effective_user.id, response_mode="brief")
        await self._safe_reply_text(update, "Режим ответа: кратко.")

    async def verbose(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        self.store.update_chat_state(update.effective_chat.id, update.effective_user.id, response_mode="verbose")
        await self._safe_reply_text(update, "Режим ответа: подробно.")

    async def voice_on(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        self.store.update_chat_state(update.effective_chat.id, update.effective_user.id, voice_replies_enabled=1)
        await self._safe_reply_text(update, "Голосовые ответы включены.")

    async def voice_off(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        self.store.update_chat_state(update.effective_chat.id, update.effective_user.id, voice_replies_enabled=0)
        await self._safe_reply_text(update, "Голосовые ответы выключены.")

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        job = self.store.get_running_job()
        if job:
            self.store.request_cancel(job.id)
            await self._safe_reply_text(update, f"Запрошена отмена задачи #{job.id}.")
            return
        queued = self.store.list_jobs(limit=1, statuses=("queued",))
        if queued:
            self.store.request_cancel(queued[0].id)
            self.store.update_job_fields(queued[0].id, status="canceled", completed_at=utc_now(), failure_reason="Canceled before start")
            await self._safe_reply_text(update, f"Отменена задача #{queued[0].id} из очереди.")
            return
        await self._safe_reply_text(update, "Нет задачи для отмены.")

    async def projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        projects = self.project_indexer.ensure_index()
        if not projects:
            await self._safe_reply_text(update, "Проекты не найдены. Запустите reindex.")
            return
        lines = [f"- {project.name}: {project.root_path}" for project in projects[:50]]
        await self._safe_reply_text(update, "Известные проекты:\n" + "\n".join(lines))

    async def use_project(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        if not context.args:
            await self._safe_reply_text(update, "Использование: /use_project <name_or_path>")
            return
        await self._switch_project(update, " ".join(context.args))

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        text = update.message.text.strip()
        intent = parse_local_intent(text)
        if intent:
            await self._handle_local_intent(update, intent.kind, intent.argument)
            return
        chat_state = self.store.get_chat_state(update.effective_chat.id)
        if chat_state and chat_state.pending_action_kind and chat_state.pending_action_resume_prompt:
            await self._handle_pending_action(update, text, chat_state.pending_action_kind)
            return
        await self._enqueue_task(update, prompt_text=text, source_type="text")

    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        if not self.stt:
            await self._safe_reply_text(update, "OPENAI_API_KEY не настроен, распознавание голоса недоступно.")
            return
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        voice = await update.message.voice.get_file()
        stem = f"voice-{update.effective_chat.id}-{update.message.message_id}"
        voice_path = self.settings.paths.voices / f"{stem}.ogg"
        transcript_path = self.settings.paths.transcripts / f"{stem}.txt"
        await voice.download_to_drive(custom_path=str(voice_path))
        try:
            transcript = self.stt.transcribe(voice_path)
        except OpenAIError:
            LOGGER.exception("Voice transcription failed")
            await self._safe_reply_text(update, "Не удалось распознать голосовое: проверь OPENAI_API_KEY для speech-to-text.")
            return
        except Exception:
            LOGGER.exception("Unexpected voice transcription failure")
            await self._safe_reply_text(update, "Ошибка при обработке голосового. Повтори позже.")
            return
        transcript_path.write_text(transcript, encoding="utf-8")
        await self._enqueue_task(
            update,
            prompt_text=transcript,
            source_type="voice",
            transcript_text=transcript,
            voice_file_path=str(voice_path),
            transcript_file_path=str(transcript_path),
        )

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        photos = update.message.photo or []
        if not photos:
            await self._safe_reply_text(update, "Фото не найдено в сообщении.")
            return
        caption = (update.message.caption or "").strip()
        image_paths = await self._download_images(update, image_kind="photo")
        await self._queue_image_batch(update, image_paths=image_paths, caption=caption, source_type="photo")

    async def handle_image_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update):
            return
        caption = (update.message.caption or "").strip()
        image_paths = await self._download_images(update, image_kind="document")
        await self._queue_image_batch(update, image_paths=image_paths, caption=caption, source_type="image_document")

    async def _handle_local_intent(self, update: Update, kind: str, argument: str | None) -> None:
        if kind == "use_project" and argument:
            await self._switch_project(update, argument)
            return
        if kind == "queue":
            await self.queue(update, None)
            return
        if kind == "current":
            await self.current(update, None)
            return
        if kind == "cancel":
            await self.cancel(update, None)
            return
        if kind == "projects":
            await self.projects(update, None)
            return
        if kind == "details":
            await self._send_last_details(update)
            return
        if kind == "brief":
            await self.brief(update, None)
            return
        if kind == "verbose":
            await self.verbose(update, None)
            return
        if kind == "voice_on":
            await self.voice_on(update, None)
            return
        if kind == "voice_off":
            await self.voice_off(update, None)
            return
        await self._enqueue_task(update, prompt_text=update.message.text.strip(), source_type="text")

    async def _switch_project(self, update: Update, target: str) -> None:
        project = self.store.find_project(target)
        if not project:
            self.project_indexer.reindex()
            project = self.store.find_project(target)
        if not project:
            await self._safe_reply_text(update, f"Проект не найден: {target}")
            return
        self.store.set_active_project(update.effective_chat.id, update.effective_user.id, project.key)
        await self._safe_reply_text(update, f"Активный проект: {project.name}\n{project.root_path}")

    async def _enqueue_task(
        self,
        update: Update,
        *,
        prompt_text: str,
        source_type: str,
        transcript_text: str | None = None,
        voice_file_path: str | None = None,
        transcript_file_path: str | None = None,
        image_file_paths: list[str] | None = None,
    ) -> None:
        project_key = self.store.get_active_project(update.effective_chat.id)
        if not project_key:
            inferred = self.project_indexer.resolve_project_hint(prompt_text)
            if inferred:
                project_key = inferred.key
                self.store.set_active_project(update.effective_chat.id, update.effective_user.id, project_key)
        if not project_key:
            project_key = self._resolve_default_project_key()
            if project_key:
                self.store.set_active_project(update.effective_chat.id, update.effective_user.id, project_key)
        artifact_dir = self.settings.paths.jobs / f"pending-{update.effective_chat.id}-{update.message.message_id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        log_path = artifact_dir / "codex.log"
        job_id = self.store.create_job(
            source_type=source_type,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            project_key=project_key,
            requested_project=project_key,
            prompt_text=prompt_text,
            transcript_text=transcript_text,
            voice_file_path=voice_file_path,
            transcript_file_path=transcript_file_path,
            image_file_paths=",".join(image_file_paths) if image_file_paths else None,
            artifact_dir=str(artifact_dir),
            log_path=str(log_path),
        )
        await self._safe_reply_text(update, f"Задача принята в очередь: #{job_id}")
        LOGGER.info("Job enqueued", extra={"job_id": job_id, "chat_id": update.effective_chat.id, "project_key": project_key})

    def _resolve_default_project_key(self) -> str | None:
        hint = (self.settings.default_project_hint or "").strip()
        if not hint:
            return None
        project = self.store.find_project(hint)
        if not project:
            self.project_indexer.reindex()
            project = self.store.find_project(hint)
        return project.key if project else None

    async def _send_last_details(self, update: Update) -> None:
        job = self.store.get_last_finished_job(update.effective_chat.id)
        if not job or not job.final_report_path or not Path(job.final_report_path).exists():
            await self._safe_reply_text(update, "Подробностей пока нет.")
            return
        report = Path(job.final_report_path).read_text(encoding="utf-8")
        status_text = self._status_text(job.status, prefix="Детали последнего ответа")
        for message in format_detailed_report_for_telegram(status_text, report):
            await update.message.reply_text(
                message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

    async def _handle_pending_action(self, update: Update, text: str, kind: str) -> None:
        state = self.store.get_chat_state(update.effective_chat.id)
        if not state or not state.pending_action_resume_prompt:
            await self._enqueue_task(update, prompt_text=text, source_type="text")
            return

        normalized = text.strip().lower()
        if kind == "confirm":
            if normalized in {"нет", "no", "n", "отмена", "cancel", "стоп"}:
                self.store.clear_pending_action(update.effective_chat.id, update.effective_user.id)
                await self._safe_reply_text(update, "Действие отменено.")
                return
            if normalized not in {"да", "yes", "y", "подтверждаю", "ок", "окей"}:
                await self._safe_reply_text(update, "Ответьте коротко: да или нет.")
                return

        self.store.clear_pending_action(update.effective_chat.id, update.effective_user.id)
        prefix = "Подтверждение пользователя" if kind == "confirm" else "Ответ пользователя на уточнение"
        prompt_text = f"{state.pending_action_resume_prompt.strip()}\n\n{prefix}: {text.strip()}"
        await self._enqueue_task(update, prompt_text=prompt_text, source_type="text")

    async def _queue_image_batch(
        self,
        update: Update,
        *,
        image_paths: list[str],
        caption: str,
        source_type: str,
    ) -> None:
        chat_id = update.effective_chat.id
        pending = self._pending_image_batches.get(chat_id)
        if pending:
            task = pending["task"]
            assert isinstance(task, asyncio.Task)
            task.cancel()
            pending_paths = pending["image_paths"]
            assert isinstance(pending_paths, list)
            pending_paths.extend(image_paths)
            if caption and not pending.get("caption"):
                pending["caption"] = caption
            if update.message.message_id > int(pending["message_id"]):
                pending["message_id"] = update.message.message_id
        else:
            pending = {
                "update": update,
                "image_paths": list(image_paths),
                "caption": caption,
                "source_type": source_type,
                "message_id": update.message.message_id,
            }
            self._pending_image_batches[chat_id] = pending

        async def finalize_batch() -> None:
            try:
                await asyncio.sleep(self.settings.image_collect_window_seconds)
                active = self._pending_image_batches.pop(chat_id, None)
                if not active:
                    return
                batch_update = active["update"]
                batch_caption = str(active.get("caption") or "").strip()
                batch_paths = list(active["image_paths"])
                prompt = batch_caption or "Реши задачу по всем приложенным изображениям как по одной общей задаче."
                await self._enqueue_task(
                    batch_update,
                    prompt_text=prompt,
                    source_type=str(active["source_type"]),
                    image_file_paths=batch_paths,
                )
            except asyncio.CancelledError:
                return

        pending["task"] = asyncio.create_task(finalize_batch())

    async def _download_images(self, update: Update, *, image_kind: str) -> list[str]:
        artifact_dir = self.settings.paths.jobs / f"pending-{update.effective_chat.id}-{update.message.message_id}"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        downloaded: list[str] = []
        if image_kind == "photo":
            file_ref = await update.message.photo[-1].get_file()
            image_path = artifact_dir / f"image-{update.message.message_id}.jpg"
            await file_ref.download_to_drive(custom_path=str(image_path))
            downloaded.append(str(image_path))
        elif image_kind == "document" and update.message.document:
            suffix = Path(update.message.document.file_name or "image.bin").suffix or ".bin"
            file_ref = await update.message.document.get_file()
            image_path = artifact_dir / f"document-{update.message.message_id}{suffix}"
            await file_ref.download_to_drive(custom_path=str(image_path))
            downloaded.append(str(image_path))
        return downloaded

    def _authorized(self, update: Update) -> bool:
        user_id = update.effective_user.id if update.effective_user else None
        chat_id = update.effective_chat.id if update.effective_chat else None
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            return False
        if self.settings.allowed_chat_ids and chat_id not in self.settings.allowed_chat_ids:
            return False
        return True

    def _status_text(self, status: str, *, prefix: str) -> str:
        return {
            "done": prefix,
            "failed": "Не получилось",
            "canceled": "Остановлено",
        }.get(status, prefix)

    async def _safe_reply_text(self, update: Update, text: str, **kwargs) -> None:
        if not update.message:
            return
        attempts = 2
        for attempt in range(attempts):
            try:
                await update.message.reply_text(text, **kwargs)
                return
            except (TimedOut, NetworkError):
                LOGGER.warning("reply_text failed", extra={"attempt": attempt + 1, "chat_id": update.effective_chat.id if update.effective_chat else None})
                if attempt + 1 >= attempts:
                    break
                await asyncio.sleep(1.5)
        if update.effective_chat:
            try:
                await update.get_bot().send_message(chat_id=update.effective_chat.id, text=text, **kwargs)
            except Exception:
                LOGGER.exception("fallback send_message failed", extra={"chat_id": update.effective_chat.id})
