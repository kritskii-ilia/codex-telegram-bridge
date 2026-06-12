from codex_telegram_bridge.reporting import (
    build_fallback_report,
    extract_final_report,
    extract_final_report_meta,
    format_detailed_report_for_telegram,
    format_report_for_telegram,
)


def test_extract_final_report() -> None:
    text = "noise\nFINAL_REPORT\nTASK_ID: 1\nPROJECT: x\nEND_FINAL_REPORT\n"
    assert extract_final_report(text) == "FINAL_REPORT\nTASK_ID: 1\nPROJECT: x\nEND_FINAL_REPORT"


def test_fallback_contains_task_id() -> None:
    report = build_fallback_report(9, "demo", "abc")
    assert "TASK_ID: 9" in report


def test_format_report_for_telegram_uses_code_blocks() -> None:
    report = (
        "FINAL_REPORT\n"
        "TASK_ID: 12\n"
        "PROJECT: demo\n"
        "SUMMARY:\nDone.\n"
        "CHANGED_FILES:\n- a.py\n- b.py\n"
        "COMMANDS_RUN:\n- pytest -q\n"
        "RESULT:\nconst x = 1;\nconsole.log(x);\n"
        "PENDING:\n- none\n"
        "RISKS:\n- none\n"
        "END_FINAL_REPORT\n"
    )
    messages = format_report_for_telegram("Задача #12 завершена", report)
    joined = "\n".join(messages)
    assert "<b>Задача #12 завершена</b>" in joined
    assert "Done." in joined
    assert "<pre><code>const x = 1;" in joined
    assert "Changed Files" not in joined
    assert "Commands Run" not in joined
    assert "Осталось" not in joined
    assert "Важно" not in joined


def test_format_report_for_telegram_splits_long_code_blocks() -> None:
    long_output = "\n".join(f"line {index}" for index in range(600))
    report = (
        "FINAL_REPORT\n"
        "TASK_ID: 1\n"
        "PROJECT: demo\n"
        "RESULT:\n"
        f"{long_output}\n"
        "END_FINAL_REPORT\n"
    )
    messages = format_report_for_telegram("status", report)
    assert len(messages) == 1
    assert "...[truncated]" in messages[0]


def test_format_report_for_telegram_shows_pending_and_risks_only_when_meaningful() -> None:
    report = (
        "FINAL_REPORT\n"
        "TASK_ID: 1\n"
        "PROJECT: demo\n"
        "SUMMARY:\nСделано.\n"
        "RESULT:\nГотово.\n"
        "PENDING:\n- Проверить результат на проде.\n"
        "RISKS:\n- Есть риск конфликта с текущими локальными правками.\n"
        "END_FINAL_REPORT\n"
    )
    messages = format_report_for_telegram("status", report)
    joined = "\n".join(messages)
    assert "<b>Осталось</b>" in joined
    assert "Проверить результат на проде." in joined
    assert "<b>Важно</b>" in joined
    assert "Есть риск конфликта" in joined


def test_extract_final_report_meta_reads_memory_and_attachments() -> None:
    report = (
        "FINAL_REPORT\n"
        "ACTION_REQUIRED:\nconfirm\n"
        "QUESTION:\nПодтвердить очистку листа?\n"
        "RESUME_PROMPT:\nПовтори исходную задачу и выполни очистку только после подтверждения.\n"
        "MEMORY_TABLE:\nЗарплаты март 2026\n"
        "MEMORY_SHEET:\nЛист3\n"
        "ATTACHMENTS:\n- exports/result.csv\n- screenshots/range.png\n"
        "DETAILS:\nОчистка затронет A2:I500.\n"
        "PENDING:\n- none\n"
        "RISKS:\n- Формулы будут заменены значениями.\n"
        "END_FINAL_REPORT\n"
    )
    meta = extract_final_report_meta(report)
    assert meta.action_required == "confirm"
    assert meta.question == "Подтвердить очистку листа?"
    assert meta.memory_table == "Зарплаты март 2026"
    assert meta.memory_sheet == "Лист3"
    assert meta.attachments == ["exports/result.csv", "screenshots/range.png"]


def test_format_detailed_report_for_telegram_includes_details_section() -> None:
    report = (
        "FINAL_REPORT\n"
        "SUMMARY:\nГотово.\n"
        "RESULT:\nОбновил 12 строк.\n"
        "DETAILS:\n- Синхронизировал A:B с H:I\n- Добавил 3 новых сотрудника\n"
        "RISKS:\n- none\n"
        "END_FINAL_REPORT\n"
    )
    messages = format_detailed_report_for_telegram("Готово", report)
    joined = "\n".join(messages)
    assert "<b>Детали</b>" in joined
    assert "Добавил 3 новых сотрудника" in joined
