from codex_telegram_bridge.intents import parse_local_intent


def test_switch_project_intent() -> None:
    intent = parse_local_intent("переключись на проект jackpot-mvp")
    assert intent
    assert intent.kind == "use_project"
    assert intent.argument == "jackpot-mvp"


def test_queue_intent() -> None:
    intent = parse_local_intent("show queue")
    assert intent
    assert intent.kind == "queue"
