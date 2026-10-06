"""Telegram Desktop ``result.json`` parser.

The parser is strict about timestamps and chat shape because fabricating a current timestamp
for malformed input can change retention decisions. It accepts both a single-chat export and
the top-level multi-chat export structure produced by Telegram Desktop.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.hashing import compute_text_hash
from tg_cleaner.core.models import ChatRecord, MessageRecord

_URL_REGEX = re.compile(r"https?://[^\s<>]+|t\.me/(?:\+|joinchat/)?[a-zA-Z0-9_\-]+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>'\""


def _extract_plain_text_and_urls(raw_text_field: str | list[Any]) -> tuple[str, list[str]]:
    """Flatten Telegram's mixed text/entity representation and extract cleaned URLs."""
    if isinstance(raw_text_field, str):
        plain_text = raw_text_field
    elif isinstance(raw_text_field, list):
        parts: list[str] = []
        for item in raw_text_field:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        plain_text = "".join(parts)
    else:
        plain_text = ""

    urls = [match.rstrip(_TRAILING_URL_PUNCTUATION) for match in _URL_REGEX.findall(plain_text)]
    return plain_text, [url for url in urls if url]


def _parse_timestamp(date_str: str | None, *, required: bool = True) -> datetime | None:
    """Parse an ISO timestamp and normalize it to naive UTC for the staging DB."""
    if not date_str:
        if required:
            raise ValueError("Telegram export message is missing its date")
        return None
    value = str(date_str).strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid Telegram export timestamp: {value!r}") from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _parse_sender_id(value: Any) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(r"(?:user|channel|chat)?(-?\d+)", str(value).strip())
    return int(match.group(1)) if match else None


def _validate_chat_payload(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return one or more chat dictionaries from supported Desktop export shapes."""
    if isinstance(data.get("messages"), list):
        return [data]
    chats = data.get("chats")
    if isinstance(chats, dict) and isinstance(chats.get("list"), list):
        chat_items = [item for item in chats["list"] if isinstance(item, dict)]
        if chat_items:
            return chat_items
    raise ValueError("Unsupported Telegram Desktop export: no chat message list was found")


def import_desktop_export_from_dict(
    data: dict[str, Any], db: DatabaseManager
) -> tuple[ChatRecord, list[MessageRecord]]:
    """Stage one chat dictionary from Telegram Desktop into SQLite."""
    if not isinstance(data.get("messages"), list):
        raise ValueError("Expected a single chat object containing a 'messages' list")

    raw_chat_id = data.get("id")
    if not isinstance(raw_chat_id, int):
        raise ValueError("Telegram export chat is missing a numeric id")
    chat_id = raw_chat_id
    chat_title = str(data.get("name") or "Telegram Export")
    chat_type = str(data.get("type") or "channel")

    messages_to_insert: list[MessageRecord] = []
    for item in data["messages"]:
        if not isinstance(item, dict) or item.get("type") == "service":
            continue
        msg_id = item.get("id")
        if not isinstance(msg_id, int):
            continue

        raw_text, urls = _extract_plain_text_and_urls(item.get("text", ""))
        file_ref = item.get("file")
        media_type = item.get("media_type")
        if not media_type and file_ref:
            media_type = "document"

        try:
            date = _parse_timestamp(item.get("date"), required=True)
            edit_date = _parse_timestamp(item.get("edited"), required=False)
        except ValueError as exc:
            raise ValueError(f"Message {msg_id}: {exc}") from exc
        assert date is not None

        messages_to_insert.append(
            MessageRecord(
                id=msg_id,
                chat_id=chat_id,
                date=date,
                edit_date=edit_date,
                sender_id=_parse_sender_id(item.get("from_id")),
                sender_name=item.get("from"),
                is_deleted_sender=False,
                text=raw_text,
                raw_text=raw_text,
                text_hash=compute_text_hash(raw_text),
                media_type=str(media_type) if media_type else None,
                media_id=str(file_ref) if file_ref else None,
                file_size=item.get("file_size") if isinstance(item.get("file_size"), int) else None,
                mime_type=item.get("mime_type"),
                duration=item.get("duration_seconds")
                if isinstance(item.get("duration_seconds"), int)
                else None,
                width=item.get("width") if isinstance(item.get("width"), int) else None,
                height=item.get("height") if isinstance(item.get("height"), int) else None,
                has_links=bool(urls),
                extracted_urls=urls,
                is_deleted_locally=False,
            )
        )

    chat_record = ChatRecord(
        id=chat_id,
        title=chat_title,
        chat_type=chat_type,
        total_messages=len(messages_to_insert),
        last_scanned=datetime.now(UTC).replace(tzinfo=None),
    )
    db.upsert_chat(chat_record)
    db.upsert_messages(messages_to_insert)
    return chat_record, messages_to_insert


def import_desktop_export_payload(
    data: dict[str, Any], db: DatabaseManager
) -> list[tuple[ChatRecord, list[MessageRecord]]]:
    """Import a single-chat or complete multi-chat Telegram Desktop payload."""
    if not isinstance(data, dict):
        raise ValueError("Telegram Desktop export root must be a JSON object")
    return [import_desktop_export_from_dict(chat_data, db) for chat_data in _validate_chat_payload(data)]


def parse_desktop_export_json(json_path: str | Path, db: DatabaseManager) -> dict[str, Any]:
    """Parse a Telegram Desktop export file and stage all supported chats."""
    file_path = Path(json_path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Export file not found: {file_path}")
    with file_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    imported = import_desktop_export_payload(data, db)
    total_messages = sum(len(messages) for _, messages in imported)
    result: dict[str, Any] = {
        "chats_imported": len(imported),
        "messages_imported": total_messages,
        "chat_ids": [chat.id for chat, _ in imported],
    }
    if len(imported) == 1:
        chat, _ = imported[0]
        result.update({"chat_id": chat.id, "chat_title": chat.title})
    return result
