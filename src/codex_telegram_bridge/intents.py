from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class ParsedIntent:
    kind: str
    argument: str | None = None


PROJECT_SWITCH_PATTERNS = [
    re.compile(r"^(?:/use_project)\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:switch to|use|continue with|return to)\s+project\s+(.+)$", re.IGNORECASE),
    re.compile(r"^(?:переключись на проект|используй проект|вернись к проекту|продолжай проект)\s+(.+)$", re.IGNORECASE),
]

CURRENT_PATTERNS = [
    re.compile(r"^(?:какой сейчас активный проект\??|current project\??)$", re.IGNORECASE),
]

QUEUE_PATTERNS = [
    re.compile(r"^(?:покажи текущую очередь|очередь|show queue|queue)$", re.IGNORECASE),
]

CANCEL_PATTERNS = [
    re.compile(r"^(?:отмени текущую задачу|cancel current|cancel)$", re.IGNORECASE),
]

PROJECTS_PATTERNS = [
    re.compile(r"^(?:список проектов|покажи проекты|projects)$", re.IGNORECASE),
]

DETAILS_PATTERNS = [
    re.compile(r"^(?:покажи детали|детали|show details|details)$", re.IGNORECASE),
]

BRIEF_PATTERNS = [
    re.compile(r"^(?:режим кратко|кратко|brief mode|brief)$", re.IGNORECASE),
]

VERBOSE_PATTERNS = [
    re.compile(r"^(?:режим подробно|подробно|verbose mode|verbose)$", re.IGNORECASE),
]

VOICE_ON_PATTERNS = [
    re.compile(r"^(?:голосовой ответ включить|включи голосовой ответ|voice replies on|voice on)$", re.IGNORECASE),
]

VOICE_OFF_PATTERNS = [
    re.compile(r"^(?:голосовой ответ выключить|выключи голосовой ответ|voice replies off|voice off)$", re.IGNORECASE),
]


def parse_local_intent(text: str) -> ParsedIntent | None:
    normalized = text.strip()
    if not normalized:
        return None
    for pattern in PROJECT_SWITCH_PATTERNS:
        match = pattern.match(normalized)
        if match:
            return ParsedIntent("use_project", match.group(1).strip())
    for pattern in CURRENT_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("current")
    for pattern in QUEUE_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("queue")
    for pattern in CANCEL_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("cancel")
    for pattern in PROJECTS_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("projects")
    for pattern in DETAILS_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("details")
    for pattern in BRIEF_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("brief")
    for pattern in VERBOSE_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("verbose")
    for pattern in VOICE_ON_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("voice_on")
    for pattern in VOICE_OFF_PATTERNS:
        if pattern.match(normalized):
            return ParsedIntent("voice_off")
    return None
