"""SQLite staging database manager for Telegram Archive Cleaner."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
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


class DatabaseManager:
    """Manages SQLite staging database with WAL mode and transaction safety."""

    def __init__(self, db_path: str = "data/cleaner.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

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
        """Check database integrity and connection."""
        try:
            with self.get_connection() as conn:
                res = conn.execute("SELECT 1;").fetchone()
                return bool(res and res[0] == 1)
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
                    chat.last_scanned or datetime.utcnow(),
                ),
            )

    def get_chat(self, chat_id: int) -> ChatRecord | None:
        """Fetch chat record by ID."""
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM chats WHERE id = ?;", (chat_id,)).fetchone()
            if not row:
                return None
            return ChatRecord(
                id=row["id"],
                title=row["title"],
                username=row["username"],
                chat_type=row["chat_type"],
                total_messages=row["total_messages"],
                last_scanned=row["last_scanned"],
            )

    def list_chats(self) -> list[ChatRecord]:
        """List all audited chats."""
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM chats ORDER BY last_scanned DESC;").fetchall()
            return [
                ChatRecord(
                    id=row["id"],
                    title=row["title"],
                    username=row["username"],
                    chat_type=row["chat_type"],
                    total_messages=row["total_messages"],
                    last_scanned=row["last_scanned"],
                )
                for row in rows
            ]

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
                    edit_date = excluded.edit_date,
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

    def get_duplicate_groups(self, chat_id: int) -> list[DuplicateGroup]:
        """Retrieve duplicate groups for a chat."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM duplicate_groups WHERE chat_id = ?;", (chat_id,)
            ).fetchall()
            groups = []
            for r in rows:
                msg_ids = json.loads(r["message_ids"]) if r["message_ids"] else []
                diff = json.loads(r["diff_summary"]) if r["diff_summary"] else {}
                groups.append(
                    DuplicateGroup(
                        id=r["id"],
                        chat_id=r["chat_id"],
                        group_type=DuplicateGroupType(r["group_type"]),
                        message_ids=msg_ids,
                        primary_message_id=r["primary_message_id"],
                        recommended_preset=RetentionPreset(r["recommended_preset"]),
                        diff_summary=diff,
                    )
                )
            return groups

    def get_duplicate_group(self, group_id: str) -> DuplicateGroup | None:
        """Retrieve a specific duplicate group by its ID."""
        with self.get_connection() as conn:
            r = conn.execute("SELECT * FROM duplicate_groups WHERE id = ?;", (group_id,)).fetchone()
            if not r:
                return None
            msg_ids = json.loads(r["message_ids"]) if r["message_ids"] else []
            diff = json.loads(r["diff_summary"]) if r["diff_summary"] else {}
            return DuplicateGroup(
                id=r["id"],
                chat_id=r["chat_id"],
                group_type=DuplicateGroupType(r["group_type"]),
                message_ids=msg_ids,
                primary_message_id=r["primary_message_id"],
                recommended_preset=RetentionPreset(r["recommended_preset"]),
                diff_summary=diff,
            )

    def upsert_flags(self, flags: list[AnalysisFlag]) -> None:
        """Batch insert analysis flags."""
        if not flags:
            return
        with self.get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO analysis_flags (
                    message_id, chat_id, flag_type, group_id,
                    is_candidate_for_deletion, confidence, details
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                [
                    (
                        f.message_id,
                        f.chat_id,
                        f.flag_type.value,
                        f.group_id,
                        1 if f.is_candidate_for_deletion else 0,
                        f.confidence,
                        json.dumps(f.details),
                    )
                    for f in flags
                ],
            )

    def update_flags_for_group(self, group_id: str, flags: list[AnalysisFlag]) -> None:
        """Replace all analysis flags for a specific duplicate group."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM analysis_flags WHERE group_id = ?;", (group_id,))
        self.upsert_flags(flags)

    def clear_flags_for_chat(self, chat_id: int) -> None:
        """Remove existing analysis flags and duplicate groups for a chat."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM analysis_flags WHERE chat_id = ?;", (chat_id,))
            conn.execute("DELETE FROM duplicate_groups WHERE chat_id = ?;", (chat_id,))

    def get_flags_for_chat(self, chat_id: int) -> list[AnalysisFlag]:
        """Fetch all audit flags for a chat."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM analysis_flags WHERE chat_id = ?;", (chat_id,)
            ).fetchall()
            flags = []
            for r in rows:
                dt = json.loads(r["details"]) if r["details"] else {}
                flags.append(
                    AnalysisFlag(
                        id=r["id"],
                        message_id=r["message_id"],
                        chat_id=r["chat_id"],
                        flag_type=FlagType(r["flag_type"]),
                        group_id=r["group_id"],
                        is_candidate_for_deletion=bool(r["is_candidate_for_deletion"]),
                        confidence=r["confidence"],
                        details=dt,
                    )
                )
            return flags

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
                (chat_id, datetime.utcnow(), backup_file, message_count, checksum),
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
        """Compute aggregated statistics for a chat."""
        with self.get_connection() as conn:
            total_msg = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE chat_id = ? AND is_deleted_locally = 0;",
                (chat_id,),
            ).fetchone()[0]

            exact_dup = conn.execute(
                """
                SELECT COUNT(DISTINCT message_id) FROM analysis_flags
                WHERE chat_id = ? AND flag_type IN ('DUPLICATE_EXACT_TEXT', 'DUPLICATE_EXACT_MEDIA');
                """,
                (chat_id,),
            ).fetchone()[0]

            same_media_diff = conn.execute(
                """
                SELECT COUNT(DISTINCT message_id) FROM analysis_flags
                WHERE chat_id = ? AND flag_type = 'DUPLICATE_SAME_MEDIA_DIFF_CAPTION';
                """,
                (chat_id,),
            ).fetchone()[0]

            dead_links = conn.execute(
                """
                SELECT COUNT(DISTINCT message_id) FROM analysis_flags
                WHERE chat_id = ? AND flag_type IN ('STALE_DEAD_LINK', 'STALE_EXPIRED_INVITE');
                """,
                (chat_id,),
            ).fetchone()[0]

            policy_restr = conn.execute(
                """
                SELECT COUNT(DISTINCT message_id) FROM analysis_flags
                WHERE chat_id = ? AND flag_type IN ('POLICY_RESTRICTED', 'POLICY_EMPTY_MEDIA', 'POLICY_DELETED_ACCOUNT');
                """,
                (chat_id,),
            ).fetchone()[0]

            cand_count = conn.execute(
                """
                SELECT COUNT(DISTINCT message_id) FROM analysis_flags
                WHERE chat_id = ? AND is_candidate_for_deletion = 1;
                """,
                (chat_id,),
            ).fetchone()[0]

            reclaimable_bytes = conn.execute(
                """
                SELECT COALESCE(SUM(m.file_size), 0) FROM messages m
                JOIN analysis_flags f ON m.chat_id = f.chat_id AND m.id = f.message_id
                WHERE m.chat_id = ? AND f.is_candidate_for_deletion = 1;
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
