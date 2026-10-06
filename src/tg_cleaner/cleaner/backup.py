"""Pre-deletion backup manager creating verified local JSON archive snapshots.

Guarantees zero data loss before any permanent Telegram message deletion.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.settings import settings


class BackupManager:
    """Manages pre-deletion JSON message backups with SHA-256 integrity verification."""

    def __init__(self, backup_dir: str | None = None) -> None:
        self.backup_dir = Path(backup_dir or settings.backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, chat_id: int, message_ids: list[int], db: DatabaseManager) -> Path:
        """Create a verifiable local JSON snapshot of specified messages."""
        if not message_ids:
            raise ValueError("Cannot create backup for empty message list")

        messages = db.get_messages(chat_id)
        id_set = set(message_ids)
        target_messages = [m for m in messages if m.id in id_set]

        messages_payload = [m.model_dump(mode="json") for m in target_messages]
        payload_bytes = json.dumps(messages_payload, sort_keys=True).encode("utf-8")
        checksum = hashlib.sha256(payload_bytes).hexdigest()

        now = datetime.now(UTC)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_dir / f"chat_{chat_id}_{timestamp_str}.json"

        snapshot_data = {
            "version": "1.0",
            "created_at": now.isoformat(),
            "chat_id": chat_id,
            "message_count": len(messages_payload),
            "sha256": checksum,
            "messages": messages_payload,
        }

        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(snapshot_data, f, indent=2, ensure_ascii=False)

        db.record_backup(
            chat_id=chat_id,
            backup_file=str(backup_file),
            message_count=len(messages_payload),
            checksum=checksum,
        )

        return backup_file

    def verify_backup(self, backup_path: Path | str) -> bool:
        """Verify the integrity and SHA-256 checksum of an existing backup file."""
        path = Path(backup_path)
        if not path.is_file():
            return False

        try:
            with open(path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)

            recorded_sha = data.get("sha256")
            messages = data.get("messages")
            if not recorded_sha or messages is None:
                return False

            payload_bytes = json.dumps(messages, sort_keys=True).encode("utf-8")
            computed_sha = hashlib.sha256(payload_bytes).hexdigest()
            return computed_sha == recorded_sha
        except Exception:
            return False

    def list_backups(self, chat_id: int | None = None) -> list[dict[str, Any]]:
        """List all valid backups in the directory."""
        results: list[dict[str, Any]] = []
        for file in sorted(self.backup_dir.glob("chat_*.json"), reverse=True):
            try:
                with open(file, encoding="utf-8") as f:
                    data = json.load(f)
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
                    }
                )
            except Exception:
                continue
        return results
