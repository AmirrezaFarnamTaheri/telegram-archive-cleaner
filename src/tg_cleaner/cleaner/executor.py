"""Delete selected messages only after backup and selection checks pass."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.core.db import DatabaseManager


class DeletionResult(BaseModel):
    """Execution summary for a deletion run."""

    chat_id: int
    total_candidates: int
    deleted_count: int
    batch_count: int
    dry_run: bool
    backup_file: str
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0


class DeletionExecutor:
    """Delete only locally known messages after verification and a checked snapshot."""

    MAX_BATCH_SIZE = 100
    DEFAULT_MIN_DELAY = 1.2
    DEFAULT_MAX_DELAY = 2.5

    def __init__(
        self,
        db: DatabaseManager,
        client: Any | None = None,
        backup_manager: BackupManager | None = None,
        min_delay: float = DEFAULT_MIN_DELAY,
        max_delay: float = DEFAULT_MAX_DELAY,
    ) -> None:
        self.db = db
        self.client = client
        self.backup_manager = backup_manager or BackupManager()
        self.min_delay = max(0.0, min_delay)
        self.max_delay = max(self.min_delay, max_delay)

    async def delete_candidates(
        self,
        chat_id: int,
        message_ids: list[int],
        dry_run: bool = False,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DeletionResult:
        """Verify scope, snapshot every request, then simulate or execute deletion."""
        if not message_ids:
            return DeletionResult(
                chat_id=chat_id,
                total_candidates=0,
                deleted_count=0,
                batch_count=0,
                dry_run=dry_run,
                backup_file="",
            )
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("Deletion request contains duplicate message IDs")

        known = self.db.get_messages_by_ids(chat_id, message_ids)
        known_ids = {message.id for message in known if not message.is_deleted_locally}
        if known_ids != set(message_ids):
            missing = sorted(set(message_ids) - known_ids)
            raise RuntimeError(
                "Deletion scope check failed; these IDs are missing, belong elsewhere, "
                f"or are already deleted: {missing}"
            )

        chunks = [
            message_ids[index : index + self.MAX_BATCH_SIZE]
            for index in range(0, len(message_ids), self.MAX_BATCH_SIZE)
        ]

        if not dry_run:
            if not self.client:
                raise ValueError("Live deletion requires an authenticated Telegram client")
            # Telethon's delete RPC does not itself prove that IDs belong to the supplied peer.
            # Resolve every target through the peer before any destructive call is made.
            await self._preflight_remote_scope(chat_id, chunks)

        start_time = time.monotonic()
        backup_file = self.backup_manager.create_backup(chat_id, message_ids, self.db)
        if not self.backup_manager.verify_backup(backup_file):
            raise RuntimeError(
                f"Safety check failed: backup verification unsuccessful for {backup_file}"
            )

        deleted_count = 0
        batch_count = 0
        for chunk in chunks:
            if dry_run:
                for message_id in chunk:
                    self.db.record_deletion_log(chat_id, message_id, "dry_run")
                deleted_count += len(chunk)
                batch_count += 1
                await asyncio.sleep(0)
            else:
                try:
                    await self._delete_live_batch(chat_id, chunk)
                except Exception as exc:
                    for message_id in chunk:
                        self.db.record_deletion_log(
                            chat_id, message_id, "failed", f"{type(exc).__name__}: {exc}"
                        )
                    raise
                self.db.mark_messages_deleted(chat_id, chunk)
                for message_id in chunk:
                    self.db.record_deletion_log(chat_id, message_id, "deleted")
                deleted_count += len(chunk)
                batch_count += 1
                if batch_count < len(chunks):
                    await asyncio.sleep(random.uniform(self.min_delay, self.max_delay))

            if progress_callback:
                progress_callback(deleted_count, len(message_ids))

        return DeletionResult(
            chat_id=chat_id,
            total_candidates=len(message_ids),
            deleted_count=deleted_count,
            batch_count=batch_count,
            dry_run=dry_run,
            backup_file=str(backup_file),
            errors=[],
            duration_seconds=round(time.monotonic() - start_time, 3),
        )

    async def _preflight_remote_scope(self, chat_id: int, chunks: list[list[int]]) -> None:
        """Resolve all requested IDs through the intended peer before deletion."""
        get_messages = getattr(self.client, "get_messages", None)
        if not callable(get_messages):
            raise RuntimeError("Telegram client cannot verify message-to-chat membership")

        for chunk in chunks:
            fetched = await get_messages(chat_id, ids=chunk)
            if fetched is None:
                fetched_list: list[Any] = []
            elif isinstance(fetched, (list, tuple)):
                fetched_list = list(fetched)
            else:
                try:
                    fetched_list = list(fetched)
                except TypeError:
                    fetched_list = [fetched]
            fetched_ids = {int(msg.id) for msg in fetched_list if getattr(msg, "id", None) is not None}
            if fetched_ids != set(chunk):
                missing = sorted(set(chunk) - fetched_ids)
                raise RuntimeError(
                    "Telegram preflight could not resolve every requested message in the selected "
                    f"chat; refusing deletion. Unresolved IDs: {missing}"
                )

    async def _delete_live_batch(
        self, chat_id: int, message_ids: list[int], max_retries: int = 3
    ) -> None:
        """Call Telegram deletion with bounded FloodWait retry handling."""
        from telethon.errors import FloodWaitError

        attempts = 0
        while True:
            try:
                await self.client.delete_messages(chat_id, message_ids, revoke=True)
                return
            except FloodWaitError as exc:
                attempts += 1
                if attempts > max_retries:
                    raise
                wait_sec = max(float(getattr(exc, "seconds", 1)) + 1.0, float(2 ** (attempts - 1)))
                await asyncio.sleep(wait_sec)
