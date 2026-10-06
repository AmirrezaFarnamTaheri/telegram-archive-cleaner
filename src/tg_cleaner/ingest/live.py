"""Telethon MTProto live message ingestor."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.hashing import compute_dhash, compute_text_hash
from tg_cleaner.core.models import ChatRecord, MessageRecord

_URL_REGEX = re.compile(r"https?://[^\s<>]+|t\.me/(?:\+|joinchat/)?[a-zA-Z0-9_\-]+", re.IGNORECASE)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}>'\""


def _utc_naive(value: datetime | None) -> datetime:
    value = value or datetime.now(UTC)
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _canonical_peer_id(entity: Any) -> int:
    """Use Telethon's marked peer id when available so dialog and message ids agree."""
    if isinstance(entity, int):
        return entity
    try:
        from telethon import utils

        return int(utils.get_peer_id(entity))
    except Exception:
        raw_id = getattr(entity, "id", None)
        if isinstance(raw_id, int):
            return raw_id
        raise ValueError("Could not determine Telegram chat id") from None


def _chat_type(entity: Any) -> str:
    if getattr(entity, "megagroup", False):
        return "supergroup"
    if getattr(entity, "broadcast", False):
        return "channel"
    if hasattr(entity, "first_name"):
        return "user"
    return "group"


class LiveIngestor:
    """Stream Telegram messages into local SQLite without reviving locally-deleted rows."""

    def __init__(self, client: Any, db: DatabaseManager, data_saver_mode: bool = True) -> None:
        self.client = client
        self.db = db
        self.data_saver_mode = data_saver_mode

    async def list_dialogs(self, limit: int = 100) -> list[ChatRecord]:
        dialogs: list[ChatRecord] = []
        async for dialog in self.client.iter_dialogs(limit=limit):
            entity = dialog.entity
            if dialog.is_user:
                chat_type = "user"
            elif dialog.is_channel and getattr(entity, "megagroup", False):
                chat_type = "supergroup"
            elif dialog.is_channel:
                chat_type = "channel"
            elif dialog.is_group:
                chat_type = "group"
            else:
                chat_type = "chat"
            dialogs.append(
                ChatRecord(
                    id=int(dialog.id),
                    title=dialog.name or "Untitled",
                    username=getattr(entity, "username", None),
                    chat_type=chat_type,
                    total_messages=int(getattr(dialog, "message_count", 0) or 0),
                    last_scanned=None,
                )
            )
        return dialogs

    async def ingest_chat(
        self,
        chat_entity: Any,
        limit: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> int:
        if limit is not None and limit <= 0:
            raise ValueError("limit must be positive or omitted")

        chat_id = _canonical_peer_id(chat_entity)
        chat_title = (
            getattr(chat_entity, "title", None)
            or getattr(chat_entity, "first_name", None)
            or getattr(chat_entity, "username", None)
            or str(chat_id)
        )
        total_hint = 0
        try:
            probe = await self.client.get_messages(chat_entity, limit=0)
            maybe_total = getattr(probe, "total", None)
            if isinstance(maybe_total, int) and maybe_total >= 0:
                total_hint = maybe_total
        except Exception:
            pass

        existing = self.db.get_chat(chat_id)
        chat_rec = ChatRecord(
            id=chat_id,
            title=str(chat_title),
            username=getattr(chat_entity, "username", None),
            chat_type=_chat_type(chat_entity),
            total_messages=max(total_hint, existing.total_messages if existing else 0),
            last_scanned=datetime.now(UTC).replace(tzinfo=None),
        )
        self.db.upsert_chat(chat_rec)

        batch: list[MessageRecord] = []
        ingested_count = 0
        batch_size = 100

        async for msg in self.client.iter_messages(chat_entity, limit=limit):
            raw_text = msg.raw_text or msg.message or ""
            urls = [u.rstrip(_TRAILING_URL_PUNCTUATION) for u in _URL_REGEX.findall(raw_text)]
            sender = getattr(msg, "sender", None)
            sender_name = None
            if sender:
                sender_name = " ".join(
                    part
                    for part in (
                        getattr(sender, "first_name", None),
                        getattr(sender, "last_name", None),
                    )
                    if part
                ) or getattr(sender, "title", None)

            media_type = None
            media_id = None
            file_size = None
            mime_type = None
            duration = None
            width = None
            height = None
            dhash_val = None

            photo = getattr(msg, "photo", None)
            document = getattr(msg, "document", None)
            if photo:
                media_type = "photo"
                media_id = str(photo.id)
                sizes = getattr(photo, "sizes", None) or []
                dimensions = [
                    (getattr(size, "w", None), getattr(size, "h", None))
                    for size in sizes
                    if isinstance(getattr(size, "w", None), int)
                    and isinstance(getattr(size, "h", None), int)
                ]
                if dimensions:
                    width, height = max(dimensions, key=lambda pair: pair[0] * pair[1])
                if not self.data_saver_mode:
                    try:
                        thumb_bytes = await self.client.download_media(msg, thumb=0, file=bytes)
                        if thumb_bytes:
                            dhash_val = compute_dhash(thumb_bytes)
                    except Exception:
                        dhash_val = None
            elif document:
                media_type = "document"
                media_id = str(document.id)
                file_size = getattr(document, "size", None)
                mime_type = getattr(document, "mime_type", None)
                for attr in getattr(document, "attributes", []):
                    attr_name = type(attr).__name__.lower()
                    if "video" in attr_name:
                        media_type = "video"
                    elif "audio" in attr_name:
                        media_type = "audio"
                    elif "sticker" in attr_name:
                        media_type = "sticker"
                    if isinstance(getattr(attr, "duration", None), int | float):
                        duration = int(attr.duration)
                    if isinstance(getattr(attr, "w", None), int):
                        width = attr.w
                    if isinstance(getattr(attr, "h", None), int):
                        height = attr.h

            fwd_from_id = None
            fwd_channel_post = None
            fwd = getattr(msg, "fwd_from", None)
            if fwd:
                from_id = getattr(fwd, "from_id", None)
                if hasattr(from_id, "channel_id"):
                    fwd_from_id = from_id.channel_id
                elif hasattr(from_id, "user_id"):
                    fwd_from_id = from_id.user_id
                elif isinstance(from_id, int):
                    fwd_from_id = from_id
                fwd_channel_post = getattr(fwd, "channel_post", None)

            restriction = getattr(msg, "restriction_reason", None)
            record = MessageRecord(
                id=int(msg.id),
                chat_id=chat_id,
                date=_utc_naive(getattr(msg, "date", None)),
                edit_date=_utc_naive(msg.edit_date) if getattr(msg, "edit_date", None) else None,
                sender_id=getattr(msg, "sender_id", None),
                sender_name=sender_name,
                is_deleted_sender=bool(getattr(sender, "deleted", False)) if sender else False,
                text=raw_text,
                raw_text=raw_text,
                text_hash=compute_text_hash(raw_text),
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
                restriction_reason=str(restriction) if restriction else None,
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
                    progress_callback(ingested_count, total_hint or limit or 0)

        if batch:
            self.db.upsert_messages(batch)
        if progress_callback:
            progress_callback(ingested_count, total_hint or limit or ingested_count)

        chat_rec.total_messages = max(total_hint, ingested_count, chat_rec.total_messages)
        self.db.upsert_chat(chat_rec)
        return ingested_count
