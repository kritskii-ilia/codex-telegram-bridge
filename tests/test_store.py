from pathlib import Path

from codex_telegram_bridge.store import BridgeStore


def test_job_lifecycle(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path / "test.sqlite3")
    store.init_db()
    job_id = store.create_job(
        source_type="text",
        chat_id=1,
        user_id=2,
        project_key=None,
        requested_project=None,
        prompt_text="hello",
    )
    job = store.claim_next_job()
    assert job
    assert job.id == job_id
    assert job.status == "running"
    store.update_job_fields(job_id, status="done")
    updated = store.get_job(job_id)
    assert updated
    assert updated.status == "done"


def test_chat_state_preferences_and_pending_action(tmp_path: Path) -> None:
    store = BridgeStore(tmp_path / "test.sqlite3")
    store.init_db()
    store.set_active_project(10, 20, "demo")
    store.update_chat_state(10, 20, response_mode="verbose", voice_replies_enabled=1, last_table_name="Таблица", last_sheet_name="Лист1")
    store.set_pending_action(10, 20, kind="confirm", question="Подтвердить?", resume_prompt="resume prompt")
    state = store.get_chat_state(10)
    assert state
    assert state.active_project_key == "demo"
    assert state.response_mode == "verbose"
    assert state.voice_replies_enabled == 1
    assert state.last_table_name == "Таблица"
    assert state.pending_action_kind == "confirm"
    store.clear_pending_action(10, 20)
    cleared = store.get_chat_state(10)
    assert cleared
    assert cleared.pending_action_kind is None
