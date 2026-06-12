from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path


FINAL_REPORT_PATTERN = re.compile(
    r"FINAL_REPORT\s*(.*?)\s*END_FINAL_REPORT",
    re.DOTALL,
)


@dataclass(slots=True)
class FinalReportMeta:
    action_required: str
    question: str
    resume_prompt: str
    memory_table: str | None
    memory_sheet: str | None
    attachments: list[str]
    details: str
    risks: str
    pending: str


def extract_final_report(text: str) -> str | None:
    match = FINAL_REPORT_PATTERN.search(text)
    if not match:
        return None
    return "FINAL_REPORT\n" + match.group(1).strip() + "\nEND_FINAL_REPORT"


def build_fallback_report(task_id: int, project: str, combined_output: str) -> str:
    tail = combined_output.strip()[-4000:] or "No output captured."
    return (
        "FINAL_REPORT\n"
        f"TASK_ID: {task_id}\n"
        f"PROJECT: {project}\n"
        "SUMMARY:\nFallback report because structured final block was not found.\n"
        "RESULT:\n"
        f"{tail}\n"
        "ACTION_REQUIRED:\nnone\n"
        "QUESTION:\nnone\n"
        "RESUME_PROMPT:\nnone\n"
        "MEMORY_TABLE:\nnone\n"
        "MEMORY_SHEET:\nnone\n"
        "ATTACHMENTS:\n- none\n"
        "DETAILS:\nStructured final block was missing; inspect worker logs if needed.\n"
        "PENDING:\n- Verify logs manually.\n"
        "RISKS:\n- Codex output did not contain FINAL_REPORT block.\n"
        "END_FINAL_REPORT\n"
    )


def save_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def format_report_for_telegram(status_text: str, final_report: str, *, mode: str = "brief") -> list[str]:
    if mode == "verbose":
        return format_detailed_report_for_telegram(status_text, final_report)

    parsed = parse_final_report(final_report)
    if not parsed:
        return [_clip_plain(status_text + "\n\n" + final_report, 3800)]

    summary = parsed.get("SUMMARY", "").strip()
    result = parsed.get("RESULT", "").strip()
    pending = _normalize_bullet_section(parsed.get("PENDING", ""))
    risks = _normalize_bullet_section(parsed.get("RISKS", ""))

    body_parts: list[str] = [f"<b>{html.escape(status_text)}</b>"]
    if summary:
        body_parts.append("")
        body_parts.append(_render_text_block(summary))
    if result:
        body_parts.append("")
        if _looks_like_code(result):
            body_parts.append(_render_code_block(result))
        else:
            body_parts.append(_render_text_block(result))
    if pending:
        body_parts.append("")
        body_parts.append("<b>Осталось</b>")
        body_parts.append(_render_text_block(pending))
    if risks:
        body_parts.append("")
        body_parts.append("<b>Важно</b>")
        body_parts.append(_render_text_block(risks))

    message = "\n".join(part for part in body_parts if part is not None).strip()
    return _split_html_messages([message])


def format_detailed_report_for_telegram(status_text: str, final_report: str) -> list[str]:
    parsed = parse_final_report(final_report)
    if not parsed:
        return [_clip_plain(status_text + "\n\n" + final_report, 3800)]

    messages: list[str] = []
    header_lines = [f"<b>{html.escape(status_text)}</b>"]

    summary = parsed.get("SUMMARY", "").strip()
    if summary:
        header_lines.append("")
        header_lines.append(_render_text_block(summary))
    messages.append("\n".join(part for part in header_lines if part is not None).strip())

    section_specs = [
        ("RESULT", "Результат", _looks_like_code(parsed.get("RESULT", ""))),
        ("DETAILS", "Детали", _looks_like_code(parsed.get("DETAILS", ""))),
        ("PENDING", "Осталось", False),
        ("RISKS", "Важно", False),
        ("CHANGED_FILES", "Изменённые файлы", True),
        ("COMMANDS_RUN", "Команды", True),
    ]
    for key, title, as_code in section_specs:
        raw = parsed.get(key, "").strip()
        normalized = _normalize_bullet_section(raw) if key in {"PENDING", "RISKS"} else raw
        if not normalized:
            continue
        rendered = _render_code_block(normalized) if as_code else _render_text_block(normalized)
        messages.append(f"<b>{title}</b>\n{rendered}")

    return _split_html_messages(messages)


def parse_final_report(report: str) -> dict[str, str]:
    lines = report.strip().splitlines()
    if not lines or lines[0].strip() != "FINAL_REPORT":
        return {}

    fields: dict[str, str] = {}
    current_key: str | None = None
    buffer: list[str] = []
    for raw_line in lines[1:]:
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if stripped == "END_FINAL_REPORT":
            break
        if ":" in line:
            key, value = line.split(":", 1)
            normalized_key = key.strip()
            if normalized_key.isupper() and normalized_key.replace("_", "").isalnum():
                if current_key is not None:
                    fields[current_key] = "\n".join(buffer).strip()
                current_key = normalized_key
                buffer = [value.strip()] if value.strip() else []
                continue
        if current_key is not None:
            buffer.append(line)
    if current_key is not None:
        fields[current_key] = "\n".join(buffer).strip()
    return fields


def extract_final_report_meta(report: str) -> FinalReportMeta:
    parsed = parse_final_report(report)
    return FinalReportMeta(
        action_required=(parsed.get("ACTION_REQUIRED", "") or "none").strip().lower(),
        question=_normalize_optional_text(parsed.get("QUESTION", "")),
        resume_prompt=_normalize_optional_text(parsed.get("RESUME_PROMPT", "")),
        memory_table=_normalize_optional_text(parsed.get("MEMORY_TABLE", "")) or None,
        memory_sheet=_normalize_optional_text(parsed.get("MEMORY_SHEET", "")) or None,
        attachments=_parse_attachment_list(parsed.get("ATTACHMENTS", "")),
        details=_normalize_optional_text(parsed.get("DETAILS", "")),
        risks=_normalize_optional_text(parsed.get("RISKS", "")),
        pending=_normalize_optional_text(parsed.get("PENDING", "")),
    )


def _render_text_block(text: str) -> str:
    escaped = html.escape(text.strip())
    return escaped.replace("\n", "<br>")


def _render_code_block(text: str) -> str:
    clipped = _clip_plain(text.strip(), 1800)
    return f"<pre><code>{html.escape(clipped)}</code></pre>"


def _looks_like_code(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    markers = ("```", "{", "}", ";", "=>", "const ", "let ", "def ", "class ", "$ ", "npm ", "pnpm ", "git ")
    if any(marker in stripped for marker in markers):
        return True
    lines = stripped.splitlines()
    if len(lines) >= 3:
        return True
    return False


def _normalize_bullet_section(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    cleaned = [line.removeprefix("-").strip() for line in lines]
    cleaned = [line for line in cleaned if line and line.lower() != "none"]
    return "\n".join(cleaned)


def _normalize_optional_text(text: str) -> str:
    stripped = text.strip()
    if not stripped or stripped.lower() == "none":
        return ""
    return _normalize_bullet_section(stripped) or stripped


def _parse_attachment_list(text: str) -> list[str]:
    normalized = _normalize_bullet_section(text)
    if not normalized:
        return []
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def _split_html_messages(messages: list[str], max_len: int = 3900) -> list[str]:
    chunks: list[str] = []
    for message in messages:
        if len(message) <= max_len:
            chunks.append(message)
            continue
        if "<pre><code>" in message and "</code></pre>" in message:
            title, _, block = message.partition("\n")
            code = block.removeprefix("<pre><code>").removesuffix("</code></pre>")
            decoded = html.unescape(code)
            for piece in _split_plain_text(decoded, 1600):
                chunks.append(f"{title}\n<pre><code>{html.escape(piece)}</code></pre>")
            continue
        for piece in _split_plain_text(html.unescape(re.sub(r"<br>", "\n", re.sub(r"<[^>]+>", "", message))), 1800):
            chunks.append(_render_text_block(piece))
    return chunks


def _split_plain_text(text: str, max_len: int) -> list[str]:
    stripped = text.strip()
    if len(stripped) <= max_len:
        return [stripped]
    parts: list[str] = []
    remaining = stripped
    while len(remaining) > max_len:
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _clip_plain(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 16] + "\n...[truncated]"
