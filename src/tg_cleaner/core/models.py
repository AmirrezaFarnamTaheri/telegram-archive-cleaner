"""Data models for Telegram Archive Cleaner."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FlagType(StrEnum):
    """Classification categories for flagged messages."""

    DUPLICATE_EXACT_TEXT = "DUPLICATE_EXACT_TEXT"
    DUPLICATE_FUZZY_TEXT = "DUPLICATE_FUZZY_TEXT"
    DUPLICATE_EXACT_MEDIA = "DUPLICATE_EXACT_MEDIA"
    DUPLICATE_VISUAL_MEDIA = "DUPLICATE_VISUAL_MEDIA"
    DUPLICATE_SAME_MEDIA_DIFF_CAPTION = "DUPLICATE_SAME_MEDIA_DIFF_CAPTION"
    DUPLICATE_FORWARD = "DUPLICATE_FORWARD"
    STALE_DEAD_LINK = "STALE_DEAD_LINK"
    STALE_EXPIRED_INVITE = "STALE_EXPIRED_INVITE"
    STALE_OUTDATED_TIME = "STALE_OUTDATED_TIME"
    STALE_SUPERSEDED_LLM = "STALE_SUPERSEDED_LLM"
    POLICY_RESTRICTED = "POLICY_RESTRICTED"
    POLICY_EMPTY_MEDIA = "POLICY_EMPTY_MEDIA"
    POLICY_DELETED_ACCOUNT = "POLICY_DELETED_ACCOUNT"


class DuplicateGroupType(StrEnum):
    """Types of detected duplicate clusters."""

    EXACT_TEXT = "EXACT_TEXT"
    FUZZY_TEXT = "FUZZY_TEXT"
    EXACT_MEDIA = "EXACT_MEDIA"
    VISUAL_SIMILAR_MEDIA = "VISUAL_SIMILAR_MEDIA"
    SAME_MEDIA_DIFF_CAPTION = "SAME_MEDIA_DIFF_CAPTION"
    FORWARD_CHAIN = "FORWARD_CHAIN"


class RetentionPreset(StrEnum):
    """Smart retention presets for duplicate resolution."""

    KEEP_NEWEST = "KEEP_NEWEST"
    KEEP_LONGEST = "KEEP_LONGEST"
    KEEP_OLDEST = "KEEP_OLDEST"
    WHITELIST_ALL = "WHITELIST_ALL"


class ChatRecord(BaseModel):
    """Metadata for an audited Telegram chat or channel."""

    id: int
    title: str
    username: str | None = None
    chat_type: str = "channel"  # "user", "channel", "supergroup", "group"
    total_messages: int = 0
    last_scanned: datetime | None = None


class MessageRecord(BaseModel):
    """Staged Telegram message record with rich media and entity metadata."""

    id: int
    chat_id: int
    date: datetime
    edit_date: datetime | None = None
    sender_id: int | None = None
    sender_name: str | None = None
    is_deleted_sender: bool = False
    text: str = ""
    raw_text: str = ""
    text_hash: str | None = None
    media_type: str | None = None
    media_id: str | None = None
    file_size: int | None = None
    mime_type: str | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    dhash: str | None = None
    fwd_from_id: int | None = None
    fwd_channel_post: int | None = None
    reply_to_msg_id: int | None = None
    restriction_reason: str | None = None
    has_links: bool = False
    extracted_urls: list[str] = Field(default_factory=list)
    is_deleted_locally: bool = False


class AnalysisFlag(BaseModel):
    """Audit finding flag on a specific message."""

    id: int | None = None
    message_id: int
    chat_id: int
    flag_type: FlagType
    group_id: str | None = None
    is_candidate_for_deletion: bool = False
    confidence: float = 1.0
    details: dict[str, Any] = Field(default_factory=dict)


class DuplicateGroup(BaseModel):
    """Clustered group of duplicate messages with diff metrics."""

    id: str
    chat_id: int
    group_type: DuplicateGroupType
    message_ids: list[int]
    primary_message_id: int | None = None
    recommended_preset: RetentionPreset = RetentionPreset.KEEP_NEWEST
    diff_summary: dict[str, Any] = Field(default_factory=dict)


class ScanStats(BaseModel):
    """Summary statistics for an audited chat."""

    chat_id: int
    total_messages: int = 0
    exact_duplicates: int = 0
    same_media_diff_caption: int = 0
    dead_links: int = 0
    policy_restricted: int = 0
    total_deletion_candidates: int = 0
    estimated_reclaimable_bytes: int = 0


class DeletionBatchRequest(BaseModel):
    """Request payload to execute a deletion batch."""

    chat_id: int
    message_ids: list[int]
    dry_run: bool = True
    create_backup: bool = True


class DeletionResult(BaseModel):
    """Execution summary of a deletion batch."""

    chat_id: int
    requested_count: int
    deleted_count: int
    failed_ids: list[int] = Field(default_factory=list)
    backup_path: str | None = None
    is_dry_run: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))
