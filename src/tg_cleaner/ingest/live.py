"""Telethon MTProto live message ingestor.

Streams chat history from Telegram directly into local SQLite staging database.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from typing import Any

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.hashing import compute_dhash, compute_text_hash
from tg_cleaner.core.models import ChatRecord, MessageRecord

_URL_REGEX = re.compile(r"https?://[^\s]+|t\.me/(?:\+|joinchat/)?[a-zA-Z0-9_\-]+", re.IGNORECASE)


class LiveIngestor:
    """Async service streaming messages from Telethon into local SQLite."""

    def __init__(self, client: Any, db: DatabaseManager, data_saver_mode: bool = True) -> None:
        self.client = client
        self.db = db
        self.data_saver_mode = data_saver_mode

    async def list_dialogs(self, limit: int = 100) -> list[ChatRecord]:
        """Fetch available chats, channels, groups, and Saved Messages."""
        dialogs = []
        async for dialog in self.client.iter_dialogs(limit=limit):
            entity = dialog.entity
            chat_id = dialog.id
            title = dialog.name or "Untitled"
            username = getattr(entity, "username", None)

            if dialog.is_user:
                chat_type = "user"
            elif dialog.is_channel:
                chat_type = "channel"
            elif dialog.is_group:
                chat_type = "group"
            else:
                chat_type = "chat"

            chat_rec = ChatRecord(
                id=chat_id,
                title=title,
                username=username,
                chat_type=chat_type,
                total_messages=getattr(dialog, "message_count", 0) or 0,
                last_scanned=None,
            )
            dialogs.append(chat_rec)
        return dialogs

    async def ingest_chat(
        self,
        chat_entity: Any,
        limit: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        """Stream messages from Telegram into local SQLite staging."""
        chat_id = getattr(chat_entity, "id", None) or (
            chat_entity if isinstance(chat_entity, int) else 0
        )
        chat_title = (
            getattr(chat_entity, "title", None)
            or getattr(chat_entity, "first_name", None)
            or str(chat_id)
        )
        chat_username = getattr(chat_entity, "username", None)

        chat_rec = ChatRecord(
            id=chat_id,
            title=chat_title,
            username=chat_username,
            chat_type="channel",
            last_scanned=datetime.utcnow(),
        )
        self.db.upsert_chat(chat_rec)

        batch: list[MessageRecord] = []
        ingested_count = 0
        batch_size = 100

        async for msg in self.client.iter_messages(chat_entity, limit=limit):
            raw_text = msg.raw_text or msg.message or ""
            urls = _URL_REGEX.findall(raw_text)
            text_hash = compute_text_hash(raw_text)

            # Sender attributes
            sender_id = msg.sender_id
            sender_name = None
            is_deleted_sender = False
            if hasattr(msg, "sender") and msg.sender:
                sender_name = getattr(msg.sender, "first_name", None)
                is_deleted_sender = getattr(msg.sender, "deleted", False) or False

            # Media attributes
            media_type = None
            media_id = None
            file_size = None
            mime_type = None
            duration = None
            width = None
            height = None
            dhash_val = None

            if msg.photo:
                media_type = "photo"
                media_id = str(msg.photo.id)
                # If not data saver mode, download micro-thumbnail (thumb=0) for dHash
                if not self.data_saver_mode:
                    try:
                        thumb_bytes = await self.client.download_media(msg, thumb=0, file=bytes)
                        if thumb_bytes:
                            dhash_val = compute_dhash(thumb_bytes)
                    except Exception:
                        dhash_val = None
            elif msg.document:
                media_type = "document"
                media_id = str(msg.document.id)
                file_size = msg.document.size
                mime_type = msg.document.mime_type
                for attr in getattr(msg.document, "attributes", []):
                    if hasattr(attr, "duration"):
                        duration = attr.duration
                        width = getattr(attr, "w", None)
                        height = getattr(attr, "h", None)

            # Forward information
            fwd_from_id = None
            fwd_channel_post = None
            if msg.fwd_from:
                fwd_from_id = getattr(msg.fwd_from, "from_id", None)
                if hasattr(fwd_from_id, "channel_id"):
                    fwd_from_id = fwd_from_id.channel_id
                elif hasattr(fwd_from_id, "user_id"):
                    fwd_from_id = fwd_from_id.user_id
                fwd_channel_post = getattr(msg.fwd_from, "channel_post", None)

            # Restriction reason
            restr_reason = None
            if getattr(msg, "restriction_reason", None):
                restr_reason = str(msg.restriction_reason)

            record = MessageRecord(
                id=msg.id,
                chat_id=chat_id,
                date=msg.date or datetime.utcnow(),
                edit_date=getattr(msg, "edit_date", None),
                sender_id=sender_id,
                sender_name=sender_name,
                is_deleted_sender=is_deleted_sender,
                text=raw_text,
                raw_text=raw_text,
                text_hash=text_hash,
                media_type=media_type,
                media_id=media_id,
                file_size=file_size,
                mime_type=mime_type,
                duration=duration,
                width=width,
                height=height,
                dhash=dhash_val,
                fwd_from_id=fwd_from_id,
                fwd_channel_post=fwd_channel_post,
                reply_to_msg_id=getattr(msg, "reply_to_msg_id", None),
                restriction_reason=restr_reason,
                has_links=bool(urls),
                extracted_urls=urls,
                is_deleted_locally=False,
            )
            batch.append(record)
            ingested_count += 1

            if len(batch) >= batch_size:
                self.db.upsert_messages(batch)
                batch.clear()
                if progress_callback:
                    progress_callback(ingested_count, limit or 0)

        if batch:
            self.db.upsert_messages(batch)
            if progress_callback:
                progress_callback(ingested_count, limit or 0)

        # Update total count on chat record
        chat_rec.total_messages = ingested_count
        self.db.upsert_chat(chat_rec)
        return ingested_count
