from __future__ import annotations

from pathlib import Path

from openai import OpenAI

from codex_telegram_bridge.config import Settings


class SpeechToTextService:
    def __init__(self, settings: Settings) -> None:
        settings.validate_for_transcription()
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_transcribe_model

    def transcribe(self, audio_path: Path) -> str:
        with audio_path.open("rb") as handle:
            transcript = self.client.audio.transcriptions.create(
                model=self.model,
                file=handle,
            )
        text = getattr(transcript, "text", "") or ""
        return text.strip()


class TextToSpeechService:
    def __init__(self, settings: Settings) -> None:
        settings.validate_for_transcription()
        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_tts_model
        self.voice = settings.openai_tts_voice

    def synthesize(self, text: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format="opus",
        )
        response.write_to_file(output_path)
        return output_path
