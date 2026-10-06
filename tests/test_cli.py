"""Tests for Typer CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from tg_cleaner.cli import app

runner = CliRunner()


def test_cli_version():
    """Verify version command prints 1.0.0."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "1.0.0" in result.stdout


def test_cli_import_and_scan_and_delete(tmp_path: Path):
    """End-to-end CLI flow: import desktop JSON, scan, and execute dry-run delete."""
    export_file = tmp_path / "export.json"
    export_data = {
        "name": "CLI Test Channel",
        "type": "public_channel",
        "id": 555,
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2026-01-01T10:00:00",
                "text": "Same text content",
            },
            {
                "id": 2,
                "type": "message",
                "date": "2026-01-01T11:00:00",
                "text": "Same text content",
            },
        ],
    }
    with open(export_file, "w", encoding="utf-8") as f:
        json.dump(export_data, f)

    db_path = str(tmp_path / "cli_test.db")

    # 1. Test import command
    res_import = runner.invoke(app, ["import", str(export_file), "--db-path", db_path])
    assert res_import.exit_code == 0
    assert "Imported 2 messages" in res_import.stdout

    # 2. Test scan command
    res_scan = runner.invoke(app, ["scan", "555", "--db-path", db_path])
    assert res_scan.exit_code == 0
    assert "Analysis complete" in res_scan.stdout
    assert "Exact duplicates:" in res_scan.stdout

    # 3. Test delete dry-run command
    res_del = runner.invoke(app, ["delete", "555", "--dry-run", "--db-path", db_path])
    assert res_del.exit_code == 0
    assert "DRY-RUN SIMULATION completed" in res_del.stdout
    assert "Backup verified" in res_del.stdout


def test_cli_main_dispatch(monkeypatch):
    """Verify main() auto-launches web dashboard with browser when zero CLI args are provided."""
    import sys
    from unittest.mock import MagicMock

    from tg_cleaner import cli

    mock_app = MagicMock()
    monkeypatch.setattr(cli, "app", mock_app)

    # 1. Zero arguments provided -> standalone GUI launch
    monkeypatch.setattr(sys, "argv", ["TelegramArchiveCleaner.exe"])
    cli.main()
    mock_app.assert_called_once_with(["web", "--open-browser"])

    # 2. CLI arguments provided -> normal CLI dispatch
    mock_app.reset_mock()
    monkeypatch.setattr(sys, "argv", ["TelegramArchiveCleaner.exe", "version"])
    cli.main()
    mock_app.assert_called_once_with()


def test_cli_get_static_dir(monkeypatch, tmp_path: Path):
    """Verify get_static_dir handles frozen MEIPASS bundles and development paths."""
    import sys

    from tg_cleaner.web.app import get_static_dir

    # 1. Normal development mode
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    static_dir = get_static_dir()
    assert static_dir.name == "static"
    assert (static_dir / "index.html").is_file()

    # 2. Frozen mode with MEIPASS bundle structure
    mock_bundle_static = tmp_path / "tg_cleaner" / "web" / "static"
    mock_bundle_static.mkdir(parents=True)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    frozen_static_dir = get_static_dir()
    assert frozen_static_dir == mock_bundle_static


def test_cli_import_multi_chat(tmp_path: Path):
    """Verify CLI import command cleanly handles multi-chat exports without KeyError."""
    export_file = tmp_path / "multi_export.json"
    export_data = {
        "chats": {
            "list": [
                {
                    "name": "Chat A",
                    "type": "channel",
                    "id": 101,
                    "messages": [
                        {
                            "id": 1,
                            "type": "message",
                            "date": "2026-01-01T10:00:00",
                            "text": "Hello A",
                        }
                    ],
                },
                {
                    "name": "Chat B",
                    "type": "channel",
                    "id": 102,
                    "messages": [
                        {
                            "id": 2,
                            "type": "message",
                            "date": "2026-01-01T10:00:00",
                            "text": "Hello B",
                        }
                    ],
                },
            ]
        }
    }
    with open(export_file, "w", encoding="utf-8") as f:
        json.dump(export_data, f)

    db_path = str(tmp_path / "multi_test.db")
    res = runner.invoke(app, ["import", str(export_file), "--db-path", db_path])
    assert res.exit_code == 0
    assert "Imported 2 messages across 2 chats" in res.stdout


def test_cli_delete_preset_only_auto_eligible(tmp_path: Path):
    """Verify that CLI delete preset only applies to auto-eligible groups, leaving fuzzy groups alone."""
    from datetime import datetime

    from tg_cleaner.core.db import DatabaseManager
    from tg_cleaner.core.models import (
        ChatRecord,
        DuplicateGroup,
        DuplicateGroupType,
        MessageRecord,
        RetentionPreset,
    )

    db_path = str(tmp_path / "test_preset.db")
    db = DatabaseManager(db_path)
    db.init_db()

    chat = ChatRecord(id=777, title="Preset Test Chat")
    db.upsert_chat(chat)

    # 1. Exact text messages
    msg1 = MessageRecord(
        id=1,
        chat_id=777,
        date=datetime(2026, 1, 1),
        text="Exact duplicate message",
        raw_text="Exact duplicate message",
    )
    msg2 = MessageRecord(
        id=2,
        chat_id=777,
        date=datetime(2026, 1, 2),
        text="Exact duplicate message",
        raw_text="Exact duplicate message",
    )
    # 2. Fuzzy text messages
    msg3 = MessageRecord(
        id=3,
        chat_id=777,
        date=datetime(2026, 1, 3),
        text="Important announcement about the workshop next Monday",
        raw_text="Important announcement about the workshop next Monday",
    )
    msg4 = MessageRecord(
        id=4,
        chat_id=777,
        date=datetime(2026, 1, 4),
        text="Important announcement regarding the workshop next Monday",
        raw_text="Important announcement regarding the workshop next Monday",
    )
    db.upsert_messages([msg1, msg2, msg3, msg4])

    grp_exact = DuplicateGroup(
        id="grp_exact",
        chat_id=777,
        group_type=DuplicateGroupType.EXACT_TEXT,
        message_ids=[1, 2],
        recommended_preset=RetentionPreset.KEEP_NEWEST,
    )
    grp_fuzzy = DuplicateGroup(
        id="grp_fuzzy",
        chat_id=777,
        group_type=DuplicateGroupType.FUZZY_TEXT,
        message_ids=[3, 4],
        recommended_preset=RetentionPreset.WHITELIST_ALL,
    )
    db.upsert_duplicate_group(grp_exact)
    db.upsert_duplicate_group(grp_fuzzy)

    # Run CLI delete with KEEP_NEWEST
    res = runner.invoke(
        app, ["delete", "777", "--preset", "KEEP_NEWEST", "--dry-run", "--db-path", db_path]
    )
    assert res.exit_code == 0
    # Only msg 1 (older of exact pair) should be candidate, NOT msg 3 (older of fuzzy pair)
    candidates = db.get_deletion_candidates(777)
    assert [c.id for c in candidates] == [1]
