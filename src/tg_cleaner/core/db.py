"""SQLite staging database manager for Telegram Archive Cleaner."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tg_cleaner.core.models import (
    AnalysisFlag,
    ChatRecord,
    DuplicateGroup,
    DuplicateGroupType,
    FlagType,
    MessageRecord,
    RetentionPreset,
    ScanStats,
)


def _adapt_datetime(value: datetime) -> str:
    """Serialize datetimes explicitly instead of relying on sqlite3 defaults."""
    return value.isoformat(sep=" ")


def _convert_datetime(raw: bytes) -> datetime:
    """Restore values written by :func:`_adapt_datetime`."""
    return datetime.fromisoformat(raw.decode("utf-8"))


def _utc_now_naive() -> datetime:
    """Return UTC while preserving the project's existing naive-datetime model."""
    return datetime.now(UTC).replace(tzinfo=None)


sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("TIMESTAMP", _convert_datetime)


class DatabaseManager:
    """Manages SQLite staging database with WAL mode and transaction safety."""

    def __init__(self, db_path: str = "data/cleaner.db") -> None:
        target_path = Path(db_path)
        try:
            if not target_path.parent.exists():
                target_path.parent.mkdir(parents=True, exist_ok=True)
            test_file = target_path.parent / ".perm_check"
            test_file.touch(exist_ok=True)
            test_file.unlink(missing_ok=True)
            self.db_path = target_path
        except (PermissionError, OSError):
            app_dir = (
                Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
                / "TelegramArchiveCleaner"
            )
            fallback_dir = app_dir / "data"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = fallback_dir / target_path.name

    def get_connection(self) -> sqlite3.Connection:
        """Create and configure a SQLite connection."""
        conn = sqlite3.connect(
            str(self.db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            timeout=30.0,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def init_db(self) -> None:
        """Initialize database schema and performance indexes."""
        with self.get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chats (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    username TEXT,
                    chat_type TEXT NOT NULL DEFAULT 'channel',
                    total_messages INTEGER DEFAULT 0,
                    last_scanned TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    date TIMESTAMP NOT NULL,
                    edit_date TIMESTAMP,
                    sender_id INTEGER,
                    sender_name TEXT,
                    is_deleted_sender BOOLEAN DEFAULT 0,
                    text TEXT DEFAULT '',
                    raw_text TEXT DEFAULT '',
                    text_hash TEXT,
                    media_type TEXT,
                    media_id TEXT,
                    file_size INTEGER,
                    mime_type TEXT,
                    duration INTEGER,
                    width INTEGER,
                    height INTEGER,
                    dhash TEXT,
                    fwd_from_id INTEGER,
                    fwd_channel_post INTEGER,
                    reply_to_msg_id INTEGER,
                    restriction_reason TEXT,
                    has_links BOOLEAN DEFAULT 0,
                    extracted_urls TEXT,
                    is_deleted_locally BOOLEAN DEFAULT 0,
                    PRIMARY KEY (chat_id, id)
                );

                CREATE INDEX IF NOT EXISTS idx_msg_chat_date ON messages(chat_id, date);
                CREATE INDEX IF NOT EXISTS idx_msg_text_hash ON messages(chat_id, text_hash);
                CREATE INDEX IF NOT EXISTS idx_msg_media_id ON messages(chat_id, media_id);
                CREATE INDEX IF NOT EXISTS idx_msg_dhash ON messages(chat_id, dhash);
                CREATE INDEX IF NOT EXISTS idx_msg_fwd ON messages(chat_id, fwd_from_id, fwd_channel_post);

                CREATE TABLE IF NOT EXISTS duplicate_groups (
                    id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    group_type TEXT NOT NULL,
                    message_ids TEXT NOT NULL,
                    primary_message_id INTEGER,
                    recommended_preset TEXT NOT NULL,
                    diff_summary TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_dup_chat ON duplicate_groups(chat_id);

                CREATE TABLE IF NOT EXISTS analysis_flags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    flag_type TEXT NOT NULL,
                    group_id TEXT,
                    is_candidate_for_deletion BOOLEAN DEFAULT 0,
                    confidence REAL DEFAULT 1.0,
                    details TEXT,
                    FOREIGN KEY (chat_id, message_id) REFERENCES messages(chat_id, id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_flags_chat_cand ON analysis_flags(chat_id, is_candidate_for_deletion);
                CREATE INDEX IF NOT EXISTS idx_flags_group ON analysis_flags(group_id);
                CREATE INDEX IF NOT EXISTS idx_msg_active_chat_date ON messages(chat_id, is_deleted_locally, date);

                -- Older builds could accumulate duplicate flags when a single analyzer was rerun.
                DELETE FROM analysis_flags
                WHERE id NOT IN (
                    SELECT MAX(id) FROM analysis_flags
                    GROUP BY chat_id, message_id, flag_type, IFNULL(group_id, '')
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_flags_unique_finding
                ON analysis_flags(chat_id, message_id, flag_type, IFNULL(group_id, ''));

                CREATE TABLE IF NOT EXISTS backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    backup_file TEXT NOT NULL,
                    message_count INTEGER NOT NULL,
                    sha256_checksum TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS deletion_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL,
                    error_message TEXT
                );
                """
            )

    def is_healthy(self) -> bool:
        """Check that SQLite can read the schema and passes a lightweight integrity check."""
        try:
            with self.get_connection() as conn:
                required = {"chats", "messages", "analysis_flags", "duplicate_groups", "backups"}
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table';"
                ).fetchall()
                if not required.issubset({row[0] for row in rows}):
                    return False
                check = conn.execute("PRAGMA quick_check;").fetchone()
                return bool(check and check[0] == "ok")
        except Exception:
            return False

    def upsert_chat(self, chat: ChatRecord) -> None:
        """Insert or update chat record."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO chats (id, title, username, chat_type, total_messages, last_scanned)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title = excluded.title,
                    username = excluded.username,
                    chat_type = excluded.chat_type,
                    total_messages = excluded.total_messages,
                    last_scanned = excluded.last_scanned;
                """,
                (
                    chat.id,
                    chat.title,
                    chat.username,
                    chat.chat_type,
                    chat.total_messages,
                    chat.last_scanned or _utc_now_naive(),
                ),
            )

    def _row_to_chat(self, row: sqlite3.Row) -> ChatRecord:
        """Convert a database row to ChatRecord model."""
        return ChatRecord(
            id=row["id"],
            title=row["title"],
            username=row["username"],
            chat_type=row["chat_type"],
            total_messages=row["total_messages"],
            last_scanned=row["last_scanned"],
        )

    def get_chat(self, chat_id: int) -> ChatRecord | None:
        """Fetch chat record by ID."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM chats WHERE id = ?;", (chat_id,)).fetchone()
            if not row:
                return None
            return self._row_to_chat(row)

    def list_chats(self) -> list[ChatRecord]:
        """List all audited chats."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM chats ORDER BY last_scanned DESC;").fetchall()
            return [self._row_to_chat(row) for row in rows]

    def upsert_messages(self, messages: list[MessageRecord]) -> None:
        """Batch upsert messages."""
        if not messages:
            return
        with self.get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO messages (
                    id, chat_id, date, edit_date, sender_id, sender_name,
                    is_deleted_sender, text, raw_text, text_hash, media_type,
                    media_id, file_size, mime_type, duration, width, height,
                    dhash, fwd_from_id, fwd_channel_post, reply_to_msg_id,
                    restriction_reason, has_links, extracted_urls, is_deleted_locally
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(chat_id, id) DO UPDATE SET
                    date = excluded.date,
                    edit_date = excluded.edit_date,
                    sender_id = excluded.sender_id,
                    sender_name = excluded.sender_name,
                    is_deleted_sender = excluded.is_deleted_sender,
                    text = excluded.text,
                    raw_text = excluded.raw_text,
                    text_hash = excluded.text_hash,
                    media_type = excluded.media_type,
                    media_id = excluded.media_id,
                    file_size = excluded.file_size,
                    mime_type = excluded.mime_type,
                    duration = excluded.duration,
                    width = excluded.width,
                    height = excluded.height,
                    dhash = excluded.dhash,
                    fwd_from_id = excluded.fwd_from_id,
                    fwd_channel_post = excluded.fwd_channel_post,
                    reply_to_msg_id = excluded.reply_to_msg_id,
                    restriction_reason = excluded.restriction_reason,
                    has_links = excluded.has_links,
                    extracted_urls = excluded.extracted_urls;
                """,
                [
                    (
                        m.id,
                        m.chat_id,
                        m.date,
                        m.edit_date,
                        m.sender_id,
                        m.sender_name,
                        1 if m.is_deleted_sender else 0,
                        m.text,
                        m.raw_text,
                        m.text_hash,
                        m.media_type,
                        m.media_id,
                        m.file_size,
                        m.mime_type,
                        m.duration,
                        m.width,
                        m.height,
                        m.dhash,
                        m.fwd_from_id,
                        m.fwd_channel_post,
                        m.reply_to_msg_id,
                        m.restriction_reason,
                        1 if m.has_links else 0,
                        json.dumps(m.extracted_urls),
                        1 if m.is_deleted_locally else 0,
                    )
                    for m in messages
                ],
            )

    def _row_to_message(self, row: sqlite3.Row) -> MessageRecord:
        urls = []
        if row["extracted_urls"]:
            try:
                urls = json.loads(row["extracted_urls"])
            except Exception:
                urls = []
        return MessageRecord(
            id=row["id"],
            chat_id=row["chat_id"],
            date=row["date"],
            edit_date=row["edit_date"],
            sender_id=row["sender_id"],
            sender_name=row["sender_name"],
            is_deleted_sender=bool(row["is_deleted_sender"]),
            text=row["text"] or "",
            raw_text=row["raw_text"] or "",
            text_hash=row["text_hash"],
            media_type=row["media_type"],
            media_id=row["media_id"],
            file_size=row["file_size"],
            mime_type=row["mime_type"],
            duration=row["duration"],
            width=row["width"],
            height=row["height"],
            dhash=row["dhash"],
            fwd_from_id=row["fwd_from_id"],
            fwd_channel_post=row["fwd_channel_post"],
            reply_to_msg_id=row["reply_to_msg_id"],
            restriction_reason=row["restriction_reason"],
            has_links=bool(row["has_links"]),
            extracted_urls=urls,
            is_deleted_locally=bool(row["is_deleted_locally"]),
        )

    def get_message(self, chat_id: int, message_id: int) -> MessageRecord | None:
        """Fetch a specific message."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE chat_id = ? AND id = ?;", (chat_id, message_id)
            ).fetchone()
            if not row:
                return None
            return self._row_to_message(row)

    def get_messages(
        self, chat_id: int, limit: int = 10000, offset: int = 0
    ) -> list[MessageRecord]:
        """Fetch messages for a chat."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE chat_id = ? ORDER BY date ASC LIMIT ? OFFSET ?;",
                (chat_id, limit, offset),
            ).fetchall()
            return [self._row_to_message(r) for r in rows]

    def get_active_messages(
        self, chat_id: int, limit: int = 10000, offset: int = 0
    ) -> list[MessageRecord]:
        """Fetch messages that have not already been deleted by this application."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages
                WHERE chat_id = ? AND is_deleted_locally = 0
                ORDER BY date ASC LIMIT ? OFFSET ?;
                """,
                (chat_id, limit, offset),
            ).fetchall()
            return [self._row_to_message(r) for r in rows]

    def get_messages_by_ids(self, chat_id: int, message_ids: list[int]) -> list[MessageRecord]:
        """Fetch messages by a list of IDs."""
        if not message_ids:
            return []
        placeholders = ",".join("?" for _ in message_ids)
        with self.get_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM messages WHERE chat_id = ? AND id IN ({placeholders});",
                [chat_id, *message_ids],
            ).fetchall()
            return [self._row_to_message(r) for r in rows]

    def upsert_duplicate_group(self, group: DuplicateGroup) -> None:
        """Insert or replace duplicate cluster."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO duplicate_groups (
                    id, chat_id, group_type, message_ids, primary_message_id,
                    recommended_preset, diff_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    group.id,
                    group.chat_id,
                    group.group_type.value,
                    json.dumps(group.message_ids),
                    group.primary_message_id,
                    group.recommended_preset.value,
                    json.dumps(group.diff_summary),
                ),
            )

    def _row_to_duplicate_group(self, row: sqlite3.Row) -> DuplicateGroup:
        """Convert a database row to DuplicateGroup model."""
        msg_ids = json.loads(row["message_ids"]) if row["message_ids"] else []
        diff = json.loads(row["diff_summary"]) if row["diff_summary"] else {}
        return DuplicateGroup(
            id=row["id"],
            chat_id=row["chat_id"],
            group_type=DuplicateGroupType(row["group_type"]),
            message_ids=msg_ids,
            primary_message_id=row["primary_message_id"],
            recommended_preset=RetentionPreset(row["recommended_preset"]),
            diff_summary=diff,
        )

    def get_duplicate_groups(self, chat_id: int) -> list[DuplicateGroup]:
        """Retrieve duplicate groups for a chat."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM duplicate_groups WHERE chat_id = ?;", (chat_id,)
            ).fetchall()
            return [self._row_to_duplicate_group(r) for r in rows]

    def get_duplicate_group(self, group_id: str) -> DuplicateGroup | None:
        """Retrieve a specific duplicate group by its ID."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM duplicate_groups WHERE id = ?;", (group_id,)).fetchone()
            if not row:
                return None
            return self._row_to_duplicate_group(row)

    @staticmethod
    def _flag_rows(flags: list[AnalysisFlag]) -> list[tuple[Any, ...]]:
        return [
            (
                f.message_id,
                f.chat_id,
                f.flag_type.value,
                f.group_id,
                1 if f.is_candidate_for_deletion else 0,
                f.confidence,
                json.dumps(f.details, ensure_ascii=False, sort_keys=True),
            )
            for f in flags
        ]

    def _upsert_flags_on_connection(
        self, conn: sqlite3.Connection, flags: list[AnalysisFlag]
    ) -> None:
        if not flags:
            return
        conn.executemany(
            """
            INSERT INTO analysis_flags (
                message_id, chat_id, flag_type, group_id,
                is_candidate_for_deletion, confidence, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO UPDATE SET
                is_candidate_for_deletion = excluded.is_candidate_for_deletion,
                confidence = excluded.confidence,
                details = excluded.details;
            """,
            self._flag_rows(flags),
        )

    def upsert_flags(self, flags: list[AnalysisFlag]) -> None:
        """Idempotently insert or refresh analysis findings."""
        if not flags:
            return
        with self.get_connection() as conn:
            self._upsert_flags_on_connection(conn, flags)

    def update_flags_for_group(self, group_id: str, flags: list[AnalysisFlag]) -> None:
        """Atomically replace all analysis flags for a specific duplicate group."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM analysis_flags WHERE group_id = ?;", (group_id,))
            self._upsert_flags_on_connection(conn, flags)

    def clear_flags_for_chat(self, chat_id: int) -> None:
        """Remove existing analysis flags and duplicate groups for a chat."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM analysis_flags WHERE chat_id = ?;", (chat_id,))
            conn.execute("DELETE FROM duplicate_groups WHERE chat_id = ?;", (chat_id,))

    def _row_to_flag(self, row: sqlite3.Row) -> AnalysisFlag:
        """Convert a database row to AnalysisFlag model."""
        details = json.loads(row["details"]) if row["details"] else {}
        return AnalysisFlag(
            id=row["id"],
            message_id=row["message_id"],
            chat_id=row["chat_id"],
            flag_type=FlagType(row["flag_type"]),
            group_id=row["group_id"],
            is_candidate_for_deletion=bool(row["is_candidate_for_deletion"]),
            confidence=row["confidence"],
            details=details,
        )

    def get_flags_for_chat(self, chat_id: int) -> list[AnalysisFlag]:
        """Fetch all audit flags for a chat."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_flags WHERE chat_id = ?;", (chat_id,)
            ).fetchall()
            return [self._row_to_flag(r) for r in rows]

    def set_message_deletion_eligibility(
        self, chat_id: int, message_id: int, eligible: bool
    ) -> int:
        """Manually approve or revoke deletion eligibility for an existing finding.

        Returns the number of findings updated. A message with no current finding cannot be
        made eligible through this method.
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE analysis_flags
                SET is_candidate_for_deletion = ?
                WHERE chat_id = ? AND message_id = ?
                  AND EXISTS (
                    SELECT 1 FROM messages m
                    WHERE m.chat_id = analysis_flags.chat_id
                      AND m.id = analysis_flags.message_id
                      AND m.is_deleted_locally = 0
                  );
                """,
                (1 if eligible else 0, chat_id, message_id),
            )
            return cursor.rowcount

    def get_deletion_candidates(self, chat_id: int) -> list[MessageRecord]:
        """Get all messages flagged as candidates for deletion."""
        with self.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT m.* FROM messages m
                JOIN analysis_flags f ON m.chat_id = f.chat_id AND m.id = f.message_id
                WHERE m.chat_id = ? AND f.is_candidate_for_deletion = 1 AND m.is_deleted_locally = 0
                ORDER BY m.date ASC;
                """,
                (chat_id,),
            ).fetchall()
            return [self._row_to_message(r) for r in rows]

    def mark_messages_deleted(self, chat_id: int, message_ids: list[int]) -> None:
        """Mark messages as deleted in local database."""
        if not message_ids:
            return
        placeholders = ",".join("?" for _ in message_ids)
        with self.get_connection() as conn:
            conn.execute(
                f"UPDATE messages SET is_deleted_locally = 1 WHERE chat_id = ? AND id IN ({placeholders});",
                [chat_id, *message_ids],
            )

    def record_deletion_log(
        self, chat_id: int, message_id: int, status: str, error_message: str | None = None
    ) -> None:
        """Persist the outcome of one attempted deletion for auditability."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO deletion_logs (chat_id, message_id, deleted_at, status, error_message)
                VALUES (?, ?, ?, ?, ?);
                """,
                (chat_id, message_id, _utc_now_naive(), status, error_message),
            )

    def list_deletion_logs(self, chat_id: int | None = None, limit: int = 500) -> list[dict[str, Any]]:
        """Return recent deletion audit records."""
        with self.get_connection() as conn:
            if chat_id is None:
                rows = conn.execute(
                    "SELECT * FROM deletion_logs ORDER BY id DESC LIMIT ?;", (limit,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM deletion_logs WHERE chat_id = ? ORDER BY id DESC LIMIT ?;",
                    (chat_id, limit),
                ).fetchall()
            return [dict(row) for row in rows]

    def record_backup(
        self, chat_id: int, backup_file: str, message_count: int, checksum: str
    ) -> None:
        """Record pre-deletion backup metadata."""
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO backups (chat_id, timestamp, backup_file, message_count, sha256_checksum)
                VALUES (?, ?, ?, ?, ?);
                """,
                (chat_id, _utc_now_naive(), backup_file, message_count, checksum),
            )

    def list_backups(self, chat_id: int | None = None) -> list[dict[str, Any]]:
        """List recorded backups."""
        with self.get_connection() as conn:
            if chat_id is not None:
                rows = conn.execute(
                    "SELECT * FROM backups WHERE chat_id = ? ORDER BY timestamp DESC;",
                    (chat_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM backups ORDER BY timestamp DESC;").fetchall()
            return [dict(r) for r in rows]

    def get_scan_stats(self, chat_id: int) -> ScanStats:
        """Compute aggregated statistics over active messages without double counting."""
        with self.get_connection() as conn:
            active_filter = "m.chat_id = ? AND m.is_deleted_locally = 0"
            total_msg = conn.execute(
                "SELECT COUNT(*) FROM messages m WHERE " + active_filter, (chat_id,)
            ).fetchone()[0]

            def count_flagged(flag_types: tuple[str, ...]) -> int:
                placeholders = ",".join("?" for _ in flag_types)
                return conn.execute(
                    f"""
                    SELECT COUNT(DISTINCT f.message_id)
                    FROM analysis_flags f
                    JOIN messages m ON m.chat_id = f.chat_id AND m.id = f.message_id
                    WHERE {active_filter} AND f.flag_type IN ({placeholders});
                    """,
                    (chat_id, *flag_types),
                ).fetchone()[0]

            exact_dup = count_flagged(("DUPLICATE_EXACT_TEXT", "DUPLICATE_EXACT_MEDIA"))
            same_media_diff = count_flagged(("DUPLICATE_SAME_MEDIA_DIFF_CAPTION",))
            dead_links = count_flagged(("STALE_DEAD_LINK", "STALE_EXPIRED_INVITE"))
            policy_restr = count_flagged(
                ("POLICY_RESTRICTED", "POLICY_EMPTY_MEDIA", "POLICY_DELETED_ACCOUNT")
            )

            cand_count = conn.execute(
                f"""
                SELECT COUNT(DISTINCT f.message_id)
                FROM analysis_flags f
                JOIN messages m ON m.chat_id = f.chat_id AND m.id = f.message_id
                WHERE {active_filter} AND f.is_candidate_for_deletion = 1;
                """,
                (chat_id,),
            ).fetchone()[0]

            reclaimable_bytes = conn.execute(
                """
                SELECT COALESCE(SUM(m.file_size), 0)
                FROM messages m
                WHERE m.chat_id = ? AND m.is_deleted_locally = 0
                  AND EXISTS (
                    SELECT 1 FROM analysis_flags f
                    WHERE f.chat_id = m.chat_id AND f.message_id = m.id
                      AND f.is_candidate_for_deletion = 1
                  );
                """,
                (chat_id,),
            ).fetchone()[0]

            return ScanStats(
                chat_id=chat_id,
                total_messages=total_msg,
                exact_duplicates=exact_dup,
                same_media_diff_caption=same_media_diff,
                dead_links=dead_links,
                policy_restricted=policy_restr,
                total_deletion_candidates=cand_count,
                estimated_reclaimable_bytes=reclaimable_bytes,
            )
