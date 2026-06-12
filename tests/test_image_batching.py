import asyncio
from types import SimpleNamespace

from codex_telegram_bridge.bot import TelegramBridgeBot


class DummyStore:
    pass


class DummyIndexer:
    pass


class DummySettings:
    openai_api_key = ""
    image_collect_window_seconds = 0.01


class DummyMessage:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class DummyChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id


class DummyUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


def test_image_batching_merges_consecutive_images(monkeypatch) -> None:
    async def scenario() -> list[dict[str, object]]:
        bot = TelegramBridgeBot(DummySettings(), DummyStore(), DummyIndexer())
        captured: list[dict[str, object]] = []

        async def fake_enqueue(update, **kwargs):
            captured.append(kwargs)

        monkeypatch.setattr(bot, "_enqueue_task", fake_enqueue)

        update1 = SimpleNamespace(effective_chat=DummyChat(1), effective_user=DummyUser(2), message=DummyMessage(10))
        update2 = SimpleNamespace(effective_chat=DummyChat(1), effective_user=DummyUser(2), message=DummyMessage(11))

        await bot._queue_image_batch(update1, image_paths=["/tmp/1.jpg"], caption="solve", source_type="photo")
        await bot._queue_image_batch(update2, image_paths=["/tmp/2.jpg"], caption="", source_type="photo")
        pending = bot._pending_image_batches[1]["task"]
        assert isinstance(pending, asyncio.Task)
        await pending
        return captured

    captured = asyncio.run(scenario())
    assert len(captured) == 1
    assert captured[0]["image_file_paths"] == ["/tmp/1.jpg", "/tmp/2.jpg"]
    assert captured[0]["prompt_text"] == "solve"
