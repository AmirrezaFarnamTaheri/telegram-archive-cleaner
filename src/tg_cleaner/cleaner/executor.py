"""Paced batch deletion executor with rate-limit protection and backup guarantees.

Part of the Application (Use Case) Layer.
"""

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
    """Executes message deletions with pre-deletion backup, 100-msg batch cap, and FloodWait backoff."""

    MAX_BATCH_SIZE: int = 100
    DEFAULT_MIN_DELAY: float = 1.2
    DEFAULT_MAX_DELAY: float = 2.5

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
        self.min_delay = min_delay
        self.max_delay = max_delay

    async def delete_candidates(
        self,
        chat_id: int,
        message_ids: list[int],
        dry_run: bool = False,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> DeletionResult:
        """Execute pre-deletion backup and paced message deletion."""
        if not message_ids:
            return DeletionResult(
                chat_id=chat_id,
                total_candidates=0,
                deleted_count=0,
                batch_count=0,
                dry_run=dry_run,
                backup_file="",
                duration_seconds=0.0,
            )

        start_time = time.monotonic()

        # Step 1: Pre-deletion JSON backup snapshot with SHA-256 verification
        backup_file = self.backup_manager.create_backup(chat_id, message_ids, self.db)
        if not self.backup_manager.verify_backup(backup_file):
            raise RuntimeError(
                f"Safety check failed: backup verification unsuccessful for {backup_file}"
            )

        # Step 2: Split into Telegram API-compliant batches (<= 100 messages)
        chunks = [
            message_ids[i : i + self.MAX_BATCH_SIZE]
            for i in range(0, len(message_ids), self.MAX_BATCH_SIZE)
        ]

        deleted_count = 0
        batch_count = 0
        errors: list[str] = []

        # Step 3: Batch deletion loop
        for chunk in chunks:
            if dry_run:
                deleted_count += len(chunk)
                batch_count += 1
                await asyncio.sleep(0.001)
            else:
                if not self.client:
                    raise ValueError("Live deletion requires an authenticated Telegram client")
                await self._delete_live_batch(chat_id, chunk)
                self.db.mark_messages_deleted(chat_id, chunk)
                deleted_count += len(chunk)
                batch_count += 1

                # Apply random jittered delay between live batches
                if batch_count < len(chunks):
                    delay = random.uniform(self.min_delay, self.max_delay)
                    await asyncio.sleep(delay)

            if progress_callback:
                progress_callback(deleted_count, len(message_ids))

        duration = time.monotonic() - start_time

        return DeletionResult(
            chat_id=chat_id,
            total_candidates=len(message_ids),
            deleted_count=deleted_count,
            batch_count=batch_count,
            dry_run=dry_run,
            backup_file=str(backup_file),
            errors=errors,
            duration_seconds=round(duration, 3),
        )

    async def _delete_live_batch(
        self, chat_id: int, message_ids: list[int], max_retries: int = 3
    ) -> None:
        """Call Telegram RPC delete_messages with automatic FloodWait backoff."""
        from telethon.errors import FloodWaitError

        attempts = 0
        while attempts <= max_retries:
            try:
                await self.client.delete_messages(chat_id, message_ids)
                return
            except FloodWaitError as e:
                attempts += 1
                if attempts > max_retries:
                    raise
                # Exponential backoff + extra 1 second safety buffer
                wait_sec = getattr(e, "seconds", 2) + 1
                await asyncio.sleep(wait_sec)
