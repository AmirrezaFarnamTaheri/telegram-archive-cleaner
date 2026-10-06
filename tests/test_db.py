"""Tests for SQLite staging database layer."""

from datetime import datetime

import pytest

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import (
    AnalysisFlag,
    ChatRecord,
    DuplicateGroup,
    DuplicateGroupType,
    FlagType,
    MessageRecord,
    RetentionPreset,
)


@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "test_stage.db"
    manager = DatabaseManager(str(db_file))
    manager.init_db()
    return manager


def test_init_db(db):
    assert db.is_healthy()


def test_upsert_chat_and_messages(db):
    chat = ChatRecord(
        id=123456,
        title="Saved Messages",
        username=None,
        chat_type="user",
        total_messages=10,
    )
    db.upsert_chat(chat)

    retrieved_chat = db.get_chat(123456)
    assert retrieved_chat is not None
    assert retrieved_chat.title == "Saved Messages"
    assert retrieved_chat.chat_type == "user"

    msg1 = MessageRecord(
        id=1,
        chat_id=123456,
        date=datetime(2026, 1, 15, 10, 0, 0),
        text="Hello world test message",
        raw_text="Hello world test message",
        text_hash="abc123hash",
        media_type=None,
    )
    msg2 = MessageRecord(
        id=2,
        chat_id=123456,
        date=datetime(2026, 1, 16, 11, 0, 0),
        text="Poster image announcement",
        raw_text="Poster image announcement",
        text_hash="def456hash",
        media_type="photo",
        media_id="photo_999",
        file_size=204800,
        mime_type="image/jpeg",
        dhash="00ffff0000ffff00",
    )
    db.upsert_messages([msg1, msg2])

    messages = db.get_messages(123456)
    assert len(messages) == 2
    assert messages[0].id == 1
    assert messages[1].media_id == "photo_999"


def test_flags_and_duplicate_groups(db):
    chat = ChatRecord(id=777, title="Resource Channel", chat_type="channel")
    db.upsert_chat(chat)

    msg1 = MessageRecord(
        id=101,
        chat_id=777,
        date=datetime(2026, 2, 1, 12, 0, 0),
        text="Conference announcement: https://conf.org/register",
        raw_text="Conference announcement: https://conf.org/register",
        text_hash="hash1",
        media_type="photo",
        media_id="shared_photo_1",
        file_size=100000,
        mime_type="image/jpeg",
    )
    msg2 = MessageRecord(
        id=102,
        chat_id=777,
        date=datetime(2026, 2, 3, 14, 0, 0),
        text="UPDATE: Conference announcement: https://conf.org/register - venue changed!",
        raw_text="UPDATE: Conference announcement: https://conf.org/register - venue changed!",
        text_hash="hash2",
        media_type="photo",
        media_id="shared_photo_1",
        file_size=100000,
        mime_type="image/jpeg",
    )
    db.upsert_messages([msg1, msg2])

    group = DuplicateGroup(
        id="group-photo-1",
        chat_id=777,
        group_type=DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION,
        message_ids=[101, 102],
        primary_message_id=102,
        recommended_preset=RetentionPreset.KEEP_NEWEST,
        diff_summary={"chars_added": 24, "has_update_marker": True},
    )
    db.upsert_duplicate_group(group)

    flag1 = AnalysisFlag(
        message_id=101,
        chat_id=777,
        flag_type=FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION,
        group_id="group-photo-1",
        is_candidate_for_deletion=True,
        confidence=1.0,
        details={"reason": "Older version with superseded caption"},
    )
    flag2 = AnalysisFlag(
        message_id=102,
        chat_id=777,
        flag_type=FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION,
        group_id="group-photo-1",
        is_candidate_for_deletion=False,
        confidence=1.0,
        details={"reason": "Newest version with updated info"},
    )
    db.upsert_flags([flag1, flag2])

    groups = db.get_duplicate_groups(777)
    assert len(groups) == 1
    assert groups[0].recommended_preset == RetentionPreset.KEEP_NEWEST

    flagged = db.get_flags_for_chat(777)
    assert len(flagged) == 2

    candidates = db.get_deletion_candidates(777)
    assert len(candidates) == 1
    assert candidates[0].id == 101


def test_mark_messages_deleted(db):
    chat = ChatRecord(id=999, title="Test Chat", chat_type="group")
    db.upsert_chat(chat)
    msg = MessageRecord(
        id=55,
        chat_id=999,
        date=datetime(2026, 3, 1),
        text="Dead link message",
        raw_text="Dead link message",
        text_hash="hash55",
    )
    db.upsert_messages([msg])

    db.mark_messages_deleted(999, [55])
    updated = db.get_message(999, 55)
    assert updated.is_deleted_locally is True
