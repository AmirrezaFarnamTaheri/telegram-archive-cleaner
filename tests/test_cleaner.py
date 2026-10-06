"""Tests for BackupManager and DeletionExecutor.

Verifies pre-deletion JSON snapshots, SHA-256 verification,
100-message batch caps, dry-run simulation, and flood-wait handling.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.cleaner.executor import DeletionExecutor
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import ChatRecord, MessageRecord


@pytest.fixture
def test_db(tmp_path: Path) -> DatabaseManager:
    """Fixture providing an isolated SQLite database."""
    db_file = tmp_path / "test_cleaner.db"
    db = DatabaseManager(str(db_file))
    db.init_db()
    chat = ChatRecord(id=1, title="Test Channel", chat_type="channel", total_messages=150)
    db.upsert_chat(chat)
    return db


@pytest.fixture
def sample_messages(test_db: DatabaseManager) -> list[MessageRecord]:
    """Insert 150 sample messages for batching tests."""
    messages = [
        MessageRecord(
            id=i,
            chat_id=1,
            date=datetime(2026, 1, 1),
            text=f"Sample message {i}",
            raw_text=f"Sample message {i}",
            media_type="photo" if i % 2 == 0 else None,
            file_size=1024 * i if i % 2 == 0 else None,
        )
        for i in range(1, 151)
    ]
    test_db.upsert_messages(messages)
    return messages


def test_backup_creation_and_integrity(
    test_db: DatabaseManager, sample_messages: list[MessageRecord], tmp_path: Path
):
    """Verify JSON backup creation, metadata, and SHA-256 verification."""
    backup_dir = tmp_path / "backups"
    manager = BackupManager(backup_dir=str(backup_dir))

    msg_ids = [1, 2, 3]
    backup_file = manager.create_backup(chat_id=1, message_ids=msg_ids, db=test_db)

    assert backup_file.exists()
    assert manager.verify_backup(backup_file) is True

    # Verify backup record in DB
    backups = test_db.list_backups(chat_id=1)
    assert len(backups) == 1
    assert backups[0]["message_count"] == 3

    # Corrupt backup content and verify failure
    with open(backup_file, "r+", encoding="utf-8") as f:
        data = json.load(f)
        data["messages"][0]["text"] = "tampered text"
        f.seek(0)
        json.dump(data, f)
        f.truncate()

    assert manager.verify_backup(backup_file) is False


@pytest.mark.asyncio
async def test_deletion_executor_dry_run(
    test_db: DatabaseManager, sample_messages: list[MessageRecord], tmp_path: Path
):
    """Verify dry-run mode creates backup, simulates deletion, and does not touch Telegram."""
    backup_dir = tmp_path / "backups"
    backup_mgr = BackupManager(backup_dir=str(backup_dir))
    mock_client = AsyncMock()

    executor = DeletionExecutor(
        db=test_db,
        client=mock_client,
        backup_manager=backup_mgr,
        min_delay=0.01,
        max_delay=0.02,
    )

    msg_ids = [1, 2, 3, 4, 5]
    result = await executor.delete_candidates(chat_id=1, message_ids=msg_ids, dry_run=True)

    assert result.dry_run is True
    assert result.deleted_count == 5
    assert result.batch_count == 1
    assert Path(result.backup_file).exists()
    # Live Telegram API must not be called
    mock_client.delete_messages.assert_not_called()

    # Messages in local DB must remain intact (not marked deleted)
    candidates = test_db.get_messages(1)
    deleted = [m for m in candidates if m.is_deleted_locally]
    assert len(deleted) == 0


@pytest.mark.asyncio
async def test_deletion_executor_live_batching(
    test_db: DatabaseManager, sample_messages: list[MessageRecord], tmp_path: Path
):
    """Verify live mode batches 150 messages into chunks of <= 100, calls client, and updates DB."""
    backup_dir = tmp_path / "backups"
    backup_mgr = BackupManager(backup_dir=str(backup_dir))
    mock_client = AsyncMock()

    executor = DeletionExecutor(
        db=test_db,
        client=mock_client,
        backup_manager=backup_mgr,
        min_delay=0.01,
        max_delay=0.02,
    )

    msg_ids = list(range(1, 151))  # 150 messages
    progress_calls = []

    def progress_callback(processed: int, total: int):
        progress_calls.append((processed, total))

    result = await executor.delete_candidates(
        chat_id=1,
        message_ids=msg_ids,
        dry_run=False,
        progress_callback=progress_callback,
    )

    assert result.dry_run is False
    assert result.deleted_count == 150
    assert result.batch_count == 2  # 100 + 50
    assert mock_client.delete_messages.call_count == 2

    # Verify first batch was 100 and second was 50
    first_call_args = mock_client.delete_messages.call_args_list[0][0]
    second_call_args = mock_client.delete_messages.call_args_list[1][0]
    assert len(first_call_args[1]) == 100
    assert len(second_call_args[1]) == 50

    # Local DB messages marked as deleted
    remaining = [m for m in test_db.get_messages(1) if not m.is_deleted_locally]
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_deletion_executor_flood_wait(
    test_db: DatabaseManager, sample_messages: list[MessageRecord], tmp_path: Path
):
    """Verify automatic exponential backoff on FloodWaitError."""
    from telethon.errors import FloodWaitError

    backup_dir = tmp_path / "backups"
    backup_mgr = BackupManager(backup_dir=str(backup_dir))
    mock_client = AsyncMock()

    # Raise flood wait once (1 sec), then succeed
    mock_client.delete_messages.side_effect = [
        FloodWaitError(request=None, capture=1),
        None,
    ]

    executor = DeletionExecutor(
        db=test_db,
        client=mock_client,
        backup_manager=backup_mgr,
        min_delay=0.01,
        max_delay=0.02,
    )

    result = await executor.delete_candidates(chat_id=1, message_ids=[1, 2], dry_run=False)

    assert result.deleted_count == 2
    assert mock_client.delete_messages.call_count == 2
