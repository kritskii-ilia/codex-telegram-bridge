from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path
from shutil import which

from codex_telegram_bridge.config import Settings
from codex_telegram_bridge.models import JobRecord, ProjectRecord
from codex_telegram_bridge.projects import ProjectIndexer
from codex_telegram_bridge.reporting import build_fallback_report, extract_final_report, save_text
from codex_telegram_bridge.store import BridgeStore


@dataclass(slots=True)
class RunResult:
    status: str
    final_report: str
    exit_code: int
    combined_output: str


FINAL_REPORT_INSTRUCTIONS = """You are running inside a local automation bridge triggered from Telegram.

Execution requirements:
1. Work autonomously in the current project directory.
2. First restore project context from README, docs, git status, and provided project memory.
3. Perform the task directly in the filesystem and terminal when needed.
4. Do not include chain-of-thought, hidden reasoning, or verbose process logs in the final answer.
5. The user sees only a rendered Telegram reply. Keep SUMMARY natural, concise, and user-facing.
6. For Google Sheets/Docs/Drive work, report applied outcomes concretely: rows updated, employees added, ranges changed, files created, conflicts found.
7. If the request is ambiguous (for example multiple similar table names or unclear target sheet), do not guess. Ask one short clarification question instead of acting.
8. If the request is risky (mass delete, clear range/sheet, overwrite formulas, destructive bulk move/rename), do not execute it yet. Ask for confirmation first.
9. When the user refers to "the same table/sheet/document", use the provided chat memory if it is relevant.
10. If you create export files, screenshots, CSVs, or other user-facing artifacts, save them inside the provided artifact directory and list them in ATTACHMENTS.
11. The final answer must be exactly one structured block in this format:

FINAL_REPORT
TASK_ID: <task id>
PROJECT: <project name or path>
SUMMARY:
<very short user-facing answer in natural language>
RESULT:
<additional useful result details in natural language, or "none">
ACTION_REQUIRED:
<none | clarify | confirm>
QUESTION:
<short question for the user if ACTION_REQUIRED is clarify/confirm, else "none">
RESUME_PROMPT:
<self-contained continuation prompt for the next run after user reply/confirmation, else "none">
MEMORY_TABLE:
<last relevant table name for chat memory, else "none">
MEMORY_SHEET:
<last relevant sheet/tab name for chat memory, else "none">
ATTACHMENTS:
- <relative or absolute artifact path, or "none">
DETAILS:
<optional deeper details for "show details", else "none">
PENDING:
- <remaining item or "none">
RISKS:
- <risk or "none">
END_FINAL_REPORT

12. The response must end immediately after END_FINAL_REPORT.
"""


class CodexRunner:
    def __init__(self, settings: Settings, store: BridgeStore, project_indexer: ProjectIndexer) -> None:
        self.settings = settings
        self.store = store
        self.project_indexer = project_indexer

    async def run_job(self, job: JobRecord, project: ProjectRecord | None) -> RunResult:
        artifact_dir = Path(job.artifact_dir or (self.settings.paths.jobs / f"job-{job.id}"))
        artifact_dir.mkdir(parents=True, exist_ok=True)
        log_path = Path(job.log_path or (artifact_dir / "codex.log"))
        last_message_path = artifact_dir / "last_message.txt"
        prompt_path = artifact_dir / "prompt.txt"

        project_name = project.name if project else "default"
        project_root = Path(project.root_path) if project else self.settings.default_project_root
        project_summary = self.project_indexer.build_project_summary(project) if project else "No active project selected."
        chat_state = self.store.get_chat_state(job.chat_id)
        wrapped_prompt = self._build_prompt(
            job=job,
            project_name=project_name,
            project_root=project_root,
            project_summary=project_summary,
            artifact_dir=artifact_dir,
            response_mode=chat_state.response_mode if chat_state else "brief",
            last_table_name=chat_state.last_table_name if chat_state else None,
            last_sheet_name=chat_state.last_sheet_name if chat_state else None,
        )
        save_text(prompt_path, wrapped_prompt)

        command = [
            *self._build_command(job=job, last_message_path=last_message_path, project_root=project_root),
        ]

        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        self.store.update_job_fields(job.id, codex_pid=process.pid, log_path=str(log_path), artifact_dir=str(artifact_dir))

        assert process.stdin is not None
        process.stdin.write(wrapped_prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()

        chunks: list[str] = []
        output_task = asyncio.create_task(self._read_output(process, chunks, log_path))
        status = "done"
        loop = asyncio.get_running_loop()
        started = loop.time()
        while process.returncode is None:
            await asyncio.sleep(1)
            current = self.store.get_job(job.id)
            if current and current.cancel_requested:
                status = "canceled"
                self._terminate_process(process.pid)
                break
            if process.returncode is not None:
                break
            if loop.time() - started > self.settings.job_timeout_seconds:
                status = "failed"
                self._terminate_process(process.pid)
                break

        await process.wait()
        await output_task
        exit_code = process.returncode if process.returncode is not None else -1
        combined_output = "".join(chunks)

        final_text = ""
        if last_message_path.exists():
            final_text = last_message_path.read_text(encoding="utf-8", errors="ignore")
        final_report = extract_final_report(final_text) or extract_final_report(combined_output)
        if not final_report:
            final_report = build_fallback_report(job.id, project_name, combined_output)
        resolved_status = status
        if resolved_status not in {"failed", "canceled"}:
            resolved_status = "done" if exit_code == 0 else "failed"
        return RunResult(status=resolved_status, final_report=final_report, exit_code=exit_code, combined_output=combined_output)

    async def _read_output(self, process: asyncio.subprocess.Process, chunks: list[str], log_path: Path) -> None:
        assert process.stdout is not None
        with log_path.open("w", encoding="utf-8") as log_handle:
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="ignore")
                chunks.append(text)
                log_handle.write(text)
                log_handle.flush()

    def _build_prompt(
        self,
        *,
        job: JobRecord,
        project_name: str,
        project_root: Path,
        project_summary: str,
        artifact_dir: Path,
        response_mode: str,
        last_table_name: str | None,
        last_sheet_name: str | None,
    ) -> str:
        downloads_hint = (
            f"- Downloads path: {self.settings.downloads_path}\n" if self.settings.downloads_path else ""
        )
        image_hints = self._build_image_hints(job)
        chat_memory_lines = [
            f"- Preferred reply mode: {response_mode}",
            f"- Last table name: {last_table_name or 'none'}",
            f"- Last sheet/tab name: {last_sheet_name or 'none'}",
            f"- Artifact directory for generated result files: {artifact_dir}",
        ]
        return (
            f"{FINAL_REPORT_INSTRUCTIONS}\n"
            f"Task metadata:\n"
            f"- Task ID: {job.id}\n"
            f"- Project name: {project_name}\n"
            f"- Project root: {project_root}\n"
            f"- Source type: {job.source_type}\n\n"
            "Environment hints:\n"
            f"{downloads_hint}"
            f"- Codex is expected to have root-capable execution: {self.settings.codex_run_as_root}\n\n"
            f"{image_hints}"
            "Chat memory:\n"
            f"{chr(10).join(chat_memory_lines)}\n\n"
            "Project memory:\n"
            f"{project_summary}\n\n"
            "Image handling requirement:\n"
            "- If multiple images are attached, treat them as one combined task and use information from all of them before answering.\n"
            "- Do not claim content is missing if it appears on another attached image.\n\n"
            "User task:\n"
            f"{job.prompt_text.strip()}\n"
        )

    def _terminate_process(self, pid: int | None) -> None:
        if not pid:
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            return

    def _build_command(self, *, job: JobRecord, last_message_path: Path, project_root: Path) -> list[str]:
        codex_command = [
            self.settings.codex_bin,
            "exec",
            "--skip-git-repo-check",
            "--output-last-message",
            str(last_message_path),
            "-C",
            str(project_root),
            "-s",
            self.settings.codex_sandbox,
            "--color",
            "never",
        ]
        if self.settings.codex_model:
            codex_command.extend(["-m", self.settings.codex_model])
        if self.settings.codex_sandbox == "danger-full-access" and self.settings.codex_approval_policy == "never":
            codex_command.append("--dangerously-bypass-approvals-and-sandbox")
        for image_path in self._job_image_paths(job):
            codex_command.extend(["-i", image_path])

        if self.settings.codex_run_as_root and os.geteuid() != 0:
            sudo_bin = which("sudo") or "/usr/bin/sudo"
            return [sudo_bin, "-n", *codex_command]
        return codex_command

    def _build_image_hints(self, job: JobRecord) -> str:
        image_paths = self._job_image_paths(job)
        if not image_paths:
            return ""
        lines = ["Attached images:"]
        lines.extend(f"- {path}" for path in image_paths)
        lines.append("")
        return "\n".join(lines)

    def _job_image_paths(self, job: JobRecord | None = None) -> list[str]:
        if job is None:
            return []
        raw = job.image_file_paths or ""
        return [item for item in (part.strip() for part in raw.split(",")) if item]
