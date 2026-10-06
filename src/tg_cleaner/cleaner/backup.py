"""Pre-deletion backup manager creating verified local JSON archive snapshots.

The backup is an execution gate, not a best-effort side effect: every requested
message must be present, the snapshot is written atomically, and the checksum is
verified before the backup is recorded as valid.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.settings import settings


class BackupManager:
    """Manage pre-deletion JSON message backups with SHA-256 verification."""

    def __init__(self, backup_dir: str | None = None) -> None:
        target_dir = Path(backup_dir or settings.backup_dir)
        try:
            if not target_dir.exists():
                target_dir.mkdir(parents=True, exist_ok=True)
            test_file = target_dir / ".perm_check"
            test_file.touch(exist_ok=True)
            test_file.unlink(missing_ok=True)
            self.backup_dir = target_dir
        except (PermissionError, OSError):
            app_dir = (
                Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
                / "TelegramArchiveCleaner"
            )
            fallback_dir = app_dir / "backups"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            self.backup_dir = fallback_dir

    @staticmethod
    def _payload_checksum(messages: list[dict[str, Any]]) -> str:
        payload_bytes = json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(payload_bytes).hexdigest()

    def create_backup(self, chat_id: int, message_ids: list[int], db: DatabaseManager) -> Path:
        """Create and verify an atomic local snapshot of exactly ``message_ids``.

        Deletion is unsafe if even one requested message is absent from the local
        staging database, so this method fails closed instead of producing a
        partial snapshot.
        """
        if not message_ids:
            raise ValueError("Cannot create backup for empty message list")

        requested_ids = [int(message_id) for message_id in message_ids]
        if len(requested_ids) != len(set(requested_ids)):
            raise ValueError("Backup request contains duplicate message IDs")

        messages = db.get_messages_by_ids(chat_id, requested_ids)
        by_id = {message.id: message for message in messages}
        missing_ids = [message_id for message_id in requested_ids if message_id not in by_id]
        if missing_ids:
            preview = ", ".join(str(message_id) for message_id in missing_ids[:10])
            suffix = "..." if len(missing_ids) > 10 else ""
            raise RuntimeError(
                "Safety check failed: cannot back up every requested message. "
                f"Missing IDs for chat {chat_id}: {preview}{suffix}"
            )

        ordered_messages = [by_id[message_id] for message_id in requested_ids]
        messages_payload = [message.model_dump(mode="json") for message in ordered_messages]
        checksum = self._payload_checksum(messages_payload)

        now = datetime.now(UTC)
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        backup_file = self.backup_dir / f"chat_{chat_id}_{timestamp}.json"
        temp_file = self.backup_dir / f".{backup_file.name}.{uuid.uuid4().hex}.tmp"

        snapshot_data = {
            "version": "1.1",
            "created_at": now.isoformat(),
            "chat_id": chat_id,
            "message_count": len(messages_payload),
            "requested_message_ids": requested_ids,
            "sha256": checksum,
            "messages": messages_payload,
        }

        try:
            with open(temp_file, "x", encoding="utf-8") as file_handle:
                json.dump(snapshot_data, file_handle, indent=2, ensure_ascii=False)
                file_handle.flush()
                os.fsync(file_handle.fileno())

            os.replace(temp_file, backup_file)

            # Best-effort directory durability on platforms that support opening directories.
            try:
                directory_fd = os.open(self.backup_dir, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except (OSError, AttributeError):
                pass

            if not self.verify_backup(backup_file):
                backup_file.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Safety check failed: backup verification unsuccessful for {backup_file}"
                )

            db.record_backup(
                chat_id=chat_id,
                backup_file=str(backup_file),
                message_count=len(messages_payload),
                checksum=checksum,
            )
            return backup_file
        finally:
            temp_file.unlink(missing_ok=True)

    def verify_backup(self, backup_path: Path | str) -> bool:
        """Verify snapshot structure, coverage metadata, and SHA-256 checksum."""
        path = Path(backup_path)
        if not path.is_file():
            return False

        try:
            with open(path, encoding="utf-8") as file_handle:
                data: dict[str, Any] = json.load(file_handle)

            recorded_sha = data.get("sha256")
            messages = data.get("messages")
            message_count = data.get("message_count")
            requested_ids = data.get("requested_message_ids")
            if not recorded_sha or not isinstance(messages, list):
                return False
            if message_count != len(messages):
                return False

            if requested_ids is not None:
                if not isinstance(requested_ids, list) or len(requested_ids) != len(messages):
                    return False
                stored_ids = [message.get("id") for message in messages]
                if stored_ids != requested_ids:
                    return False

            computed_sha = self._payload_checksum(messages)
            if computed_sha == recorded_sha:
                return True
            if data.get("version") in (None, "1.0"):
                legacy_bytes = json.dumps(messages, sort_keys=True).encode("utf-8")
                return hashlib.sha256(legacy_bytes).hexdigest() == recorded_sha
            return False
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False

    def list_backups(self, chat_id: int | None = None) -> list[dict[str, Any]]:
        """List checksum-valid backups in reverse chronological filename order."""
        results: list[dict[str, Any]] = []
        for file in sorted(self.backup_dir.glob("chat_*.json"), reverse=True):
            try:
                if not self.verify_backup(file):
                    continue
                with open(file, encoding="utf-8") as file_handle:
                    data = json.load(file_handle)
                file_chat_id = data.get("chat_id")
                if chat_id is not None and file_chat_id != chat_id:
                    continue
                results.append(
                    {
                        "path": str(file),
                        "filename": file.name,
                        "chat_id": file_chat_id,
                        "created_at": data.get("created_at"),
                        "message_count": data.get("message_count", 0),
                        "sha256": data.get("sha256"),
                        "size_bytes": file.stat().st_size,
                        "verified": True,
                    }
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        return results
