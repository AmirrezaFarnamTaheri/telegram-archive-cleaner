"""Telegram Desktop machine-readable export parser (result.json).

Converts offline export archives into domain MessageRecord and ChatRecord entities.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.hashing import compute_text_hash
from tg_cleaner.core.models import ChatRecord, MessageRecord

# URL matching pattern
_URL_REGEX = re.compile(r"https?://[^\s]+|t\.me/(?:\+|joinchat/)?[a-zA-Z0-9_\-]+", re.IGNORECASE)


def _extract_plain_text_and_urls(raw_text_field: str | list[Any]) -> tuple[str, list[str]]:
    """Extract plain text string and URLs from Telegram Desktop mixed entity formats."""
    if isinstance(raw_text_field, str):
        plain_text = raw_text_field
    elif isinstance(raw_text_field, list):
        parts = []
        for item in raw_text_field:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        plain_text = "".join(parts)
    else:
        plain_text = ""

    urls = _URL_REGEX.findall(plain_text)
    return plain_text, urls


def _parse_timestamp(date_str: str | None) -> datetime:
    """Parse ISO datetime string from export."""
    if not date_str:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return datetime.utcnow()


def import_desktop_export_from_dict(
    data: dict[str, Any], db: DatabaseManager
) -> tuple[ChatRecord, list[MessageRecord]]:
    """Stage chat and messages from Telegram Desktop export data dictionary into SQLite."""
    chat_id = data.get("id", 0)
    chat_title = data.get("name", "Telegram Export")
    chat_type = data.get("type", "channel")

    chat_record = ChatRecord(
        id=chat_id,
        title=chat_title,
        chat_type=chat_type,
        total_messages=len(data.get("messages", [])),
        last_scanned=datetime.utcnow(),
    )
    db.upsert_chat(chat_record)

    messages_to_insert: list[MessageRecord] = []
    raw_messages = data.get("messages", [])

    for item in raw_messages:
        if item.get("type") == "service":
            continue

        msg_id = item.get("id")
        if msg_id is None:
            continue

        raw_text, urls = _extract_plain_text_and_urls(item.get("text", ""))
        text_hash = compute_text_hash(raw_text)

        media_type = item.get("media_type")
        file_ref = item.get("file")
        width = item.get("width")
        height = item.get("height")
        duration = item.get("duration_seconds")
        mime_type = item.get("mime_type")

        if not media_type and file_ref:
            media_type = "document"

        media_id = str(file_ref) if file_ref else None

        msg_record = MessageRecord(
            id=msg_id,
            chat_id=chat_id,
            date=_parse_timestamp(item.get("date")),
            edit_date=_parse_timestamp(item.get("edited")) if item.get("edited") else None,
            sender_id=int(item.get("from_id").replace("user", ""))
            if str(item.get("from_id", "")).startswith("user")
            else None,
            sender_name=item.get("from"),
            is_deleted_sender=False,
            text=raw_text,
            raw_text=raw_text,
            text_hash=text_hash,
            media_type=media_type,
            media_id=media_id,
            file_size=item.get("file_size"),
            mime_type=mime_type,
            duration=duration,
            width=width,
            height=height,
            has_links=bool(urls),
            extracted_urls=urls,
            is_deleted_locally=False,
        )
        messages_to_insert.append(msg_record)

    db.upsert_messages(messages_to_insert)
    return chat_record, messages_to_insert


def parse_desktop_export_json(json_path: str | Path, db: DatabaseManager) -> dict[str, Any]:
    """Parse a Telegram Desktop export file and stage chats and messages into SQLite."""
    file_path = Path(json_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Export file not found: {file_path}")

    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)

    chat_record, messages = import_desktop_export_from_dict(data, db)
    return {
        "chat_id": chat_record.id,
        "chat_title": chat_record.title,
        "messages_imported": len(messages),
    }
