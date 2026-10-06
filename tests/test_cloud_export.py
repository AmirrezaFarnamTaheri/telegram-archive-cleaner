"""Tests for cloud export manager."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.cleaner.cloud_export import CloudExportManager
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import ChatRecord, MessageRecord


@pytest.fixture
def mock_db(tmp_path: Path) -> DatabaseManager:
    """Fixture providing a temporary SQLite database with test messages."""
    db = DatabaseManager(str(tmp_path / "test.db"))
    db.init_db()
    db.upsert_chat(ChatRecord(id=100, title="Export Test Chat", chat_type="channel"))
    db.upsert_chat(ChatRecord(id=200, title="Drive Test Chat", chat_type="channel"))
    msg1 = MessageRecord(
        id=1,
        chat_id=100,
        date=datetime.now(UTC),
        text="Hello GitHub Export",
    )
    msg2 = MessageRecord(
        id=1,
        chat_id=200,
        date=datetime.now(UTC),
        text="Drive Backup Test",
    )
    db.upsert_messages([msg1, msg2])
    return db


@pytest.mark.asyncio
@respx.mock
async def test_cloud_export_github(mock_db: DatabaseManager, tmp_path: Path):
    """Test exporting verified backup to GitHub Contents API."""
    backup_dir = tmp_path / "backups"
    backup_mgr = BackupManager(backup_dir=str(backup_dir))

    file_path = backup_mgr.create_backup(chat_id=100, message_ids=[1], db=mock_db)

    # Mock GitHub API
    route = respx.put(
        f"https://api.github.com/repos/testuser/backups/contents/telegram-backups/{file_path.name}"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "content": {
                    "sha": "github_blob_sha_123",
                    "html_url": "https://github.com/testuser/backups/blob/main/backup.json",
                }
            },
        )
    )

    exporter = CloudExportManager(backup_dir=backup_dir)
    res = await exporter.export_to_github(
        backup_filename=file_path.name,
        token="test_gh_token",
        repo="testuser/backups",
        branch="main",
    )

    assert res.success is True
    assert res.provider == "github"
    assert res.file_id == "github_blob_sha_123"
    assert res.sha256 != ""
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_cloud_export_google_drive(mock_db: DatabaseManager, tmp_path: Path):
    """Test exporting backup to Google Drive resumable session."""
    backup_dir = tmp_path / "backups"
    backup_mgr = BackupManager(backup_dir=str(backup_dir))

    file_path = backup_mgr.create_backup(chat_id=200, message_ids=[1], db=mock_db)

    # Mock Drive session init
    respx.post("https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable").mock(
        return_value=httpx.Response(
            200,
            headers={
                "Location": "https://www.googleapis.com/upload/drive/v3/files?upload_id=session_xyz"
            },
        )
    )

    # Mock Drive upload PUT
    respx.put("https://www.googleapis.com/upload/drive/v3/files?upload_id=session_xyz").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "drive_file_id_999",
                "webViewLink": "https://drive.google.com/file/d/drive_file_id_999/view",
            },
        )
    )

    exporter = CloudExportManager(backup_dir=backup_dir)
    res = await exporter.export_to_google_drive(
        backup_filename=file_path.name,
        access_token="test_oauth_token",
    )

    assert res.success is True
    assert res.provider == "google_drive"
    assert res.file_id == "drive_file_id_999"
    assert res.sha256 != ""
