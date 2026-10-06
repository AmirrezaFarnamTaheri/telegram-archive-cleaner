"""Unit tests for ingestion subsystem (Telegram Desktop export and live client)."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.ingest.desktop_export import parse_desktop_export_json
from tg_cleaner.ingest.live import LiveIngestor


@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "test_ingest.db"
    manager = DatabaseManager(str(db_file))
    manager.init_db()
    return manager


@pytest.fixture
def sample_desktop_json(tmp_path):
    """Create a realistic Telegram Desktop result.json file."""
    data = {
        "name": "Design & Tech Archive",
        "type": "public_channel",
        "id": 987654321,
        "messages": [
            {
                "id": 1001,
                "type": "message",
                "date": "2026-02-10T14:30:00",
                "from": "Admin",
                "from_id": "user111",
                "text": "Hello world welcome to the channel: https://example.com/welcome",
            },
            {
                "id": 1002,
                "type": "message",
                "date": "2026-02-11T09:15:00",
                "from": "Admin",
                "from_id": "user111",
                "file": "photos/poster.jpg",
                "media_type": "photo",
                "width": 1920,
                "height": 1080,
                # Rich text entity array format used by Telegram Desktop
                "text": [
                    "Event flyer: ",
                    {"type": "link", "text": "https://event.io/register"},
                    " See you there!",
                ],
            },
            {
                "id": 1003,
                "type": "message",
                "date": "2026-02-12T11:00:00",
                "from": "Admin",
                "from_id": "user111",
                "file": "photos/poster.jpg",
                "media_type": "photo",
                "width": 1920,
                "height": 1080,
                # Same photo, updated caption!
                "text": "UPDATE: Event flyer! Rescheduled to next week: https://event.io/new-link",
            },
            {
                "id": 1004,
                "type": "service",  # Service message (pinned message, etc.) - should be filtered or flagged
                "action": "pin_message",
                "date": "2026-02-12T11:05:00",
                "actor": "Admin",
                "text": "",
            },
        ],
    }
    json_path = tmp_path / "result.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return json_path


def test_parse_desktop_export_json(db, sample_desktop_json):
    # Act
    stats = parse_desktop_export_json(sample_desktop_json, db)

    # Assert
    assert stats["chat_id"] == 987654321
    assert stats["chat_title"] == "Design & Tech Archive"
    assert stats["messages_imported"] == 3  # 3 standard messages, 1 service skipped

    messages = db.get_messages(987654321)
    assert len(messages) == 3

    # Check text message
    msg1 = messages[0]
    assert msg1.id == 1001
    assert "https://example.com/welcome" in msg1.extracted_urls
    assert msg1.has_links is True
    assert msg1.text_hash is not None

    # Check rich-entity text resolution
    msg2 = messages[1]
    assert msg2.id == 1002
    assert msg2.media_type == "photo"
    assert msg2.width == 1920
    assert "https://event.io/register" in msg2.extracted_urls
    assert "Event flyer: https://event.io/register See you there!" in msg2.raw_text

    # Check same media different caption message
    msg3 = messages[2]
    assert msg3.id == 1003
    assert msg3.media_type == "photo"
    assert msg3.file_size is not None or msg3.width == 1920
    assert "UPDATE" in msg3.text


@pytest.mark.asyncio
async def test_live_ingestor_with_mock_client(db):
    # Arrange: Mock Telethon client and message objects
    mock_client = AsyncMock()

    mock_chat = MagicMock()
    mock_chat.id = 555123
    mock_chat.title = "Mock Channel"
    mock_chat.username = "mockchan"

    mock_msg1 = MagicMock()
    mock_msg1.id = 1
    mock_msg1.date = datetime(2026, 3, 1, 10, 0, 0)
    mock_msg1.edit_date = None
    mock_msg1.sender_id = 99
    mock_msg1.sender = MagicMock(first_name="Alice", last_name=None, deleted=False)
    mock_msg1.message = "Hello from Telethon"
    mock_msg1.raw_text = "Hello from Telethon"
    mock_msg1.media = None
    mock_msg1.photo = None
    mock_msg1.document = None
    mock_msg1.fwd_from = None
    mock_msg1.reply_to_msg_id = None
    mock_msg1.restriction_reason = None

    async def mock_iter_messages(entity, limit=None):
        yield mock_msg1

    mock_client.iter_messages = mock_iter_messages

    # Act
    ingestor = LiveIngestor(mock_client, db)
    count = await ingestor.ingest_chat(mock_chat, limit=10)

    # Assert
    assert count == 1
    stored = db.get_messages(555123)
    assert len(stored) == 1
    assert stored[0].text == "Hello from Telethon"
    assert stored[0].chat_id == 555123


def test_desktop_export_rejects_placeholder_file_strings(db, tmp_path):
    """Verify that export placeholder strings like (File not included...) are discarded as media IDs."""
    data = {
        "name": "Placeholder Test",
        "type": "public_channel",
        "id": 112233,
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date": "2026-02-10T14:30:00",
                "text": "File not downloaded locally",
                "file": "(File not included. Change data exporting settings to download.)",
            }
        ],
    }
    json_path = tmp_path / "placeholder.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    parse_desktop_export_json(json_path, db)
    msg = db.get_message(112233, 1)
    assert msg is not None
    assert msg.media_id is None
