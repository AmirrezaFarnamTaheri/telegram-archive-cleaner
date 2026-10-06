"""Unit tests for the multi-engine DeduplicationEngine.

Tests exact text, exact media, fuzzy text, and Same Media / Different Caption clustering.
"""

from datetime import datetime

import pytest

from tg_cleaner.analyzer.dedupe import DeduplicationEngine
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.hashing import compute_text_hash
from tg_cleaner.core.models import (
    ChatRecord,
    DuplicateGroupType,
    MessageRecord,
    RetentionPreset,
)


@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "test_dedupe.db"
    manager = DatabaseManager(str(db_file))
    manager.init_db()
    return manager


@pytest.fixture
def engine(db):
    return DeduplicationEngine(db)


def test_exact_text_duplicates(db, engine):
    # Arrange
    chat = ChatRecord(id=1, title="Test Chat")
    db.upsert_chat(chat)

    msg1 = MessageRecord(
        id=10,
        chat_id=1,
        date=datetime(2026, 1, 1, 10, 0),
        text="Weekly reminder: All hands meeting at 4 PM.",
        raw_text="Weekly reminder: All hands meeting at 4 PM.",
        text_hash=compute_text_hash("Weekly reminder: All hands meeting at 4 PM."),
    )
    msg2 = MessageRecord(
        id=20,
        chat_id=1,
        date=datetime(2026, 1, 8, 10, 0),
        text="weekly reminder: all hands meeting at 4 pm.",
        raw_text="weekly reminder: all hands meeting at 4 pm.",
        text_hash=compute_text_hash("weekly reminder: all hands meeting at 4 pm."),
    )
    db.upsert_messages([msg1, msg2])

    # Act
    groups = engine.find_duplicates(1, preset=RetentionPreset.KEEP_NEWEST)

    # Assert
    assert len(groups) == 1
    group = groups[0]
    assert group.group_type == DuplicateGroupType.EXACT_TEXT
    assert set(group.message_ids) == {10, 20}
    assert group.primary_message_id == 20  # KEEP_NEWEST preserves msg2 (id 20)

    # Check candidates for deletion in db
    candidates = db.get_deletion_candidates(1)
    assert len(candidates) == 1
    assert candidates[0].id == 10  # msg1 flagged for deletion


def test_same_media_different_captions_with_presets(db, engine):
    # Arrange: Exact same photo posted twice with an updated reschedule notice
    chat = ChatRecord(id=2, title="Channel")
    db.upsert_chat(chat)

    msg1 = MessageRecord(
        id=101,
        chat_id=2,
        date=datetime(2026, 2, 1, 12, 0),
        text="Webinar on AI Agents this Friday: https://event.com/ai",
        raw_text="Webinar on AI Agents this Friday: https://event.com/ai",
        text_hash=compute_text_hash("Webinar on AI Agents this Friday: https://event.com/ai"),
        media_type="photo",
        media_id="photo_xyz_99",
        width=1280,
        height=720,
    )
    msg2 = MessageRecord(
        id=102,
        chat_id=2,
        date=datetime(2026, 2, 3, 14, 0),
        text="UPDATE: Webinar RESCHEDULED to Monday: https://event.com/ai-updated (Extended Q&A)",
        raw_text="UPDATE: Webinar RESCHEDULED to Monday: https://event.com/ai-updated (Extended Q&A)",
        text_hash=compute_text_hash(
            "UPDATE: Webinar RESCHEDULED to Monday: https://event.com/ai-updated (Extended Q&A)"
        ),
        media_type="photo",
        media_id="photo_xyz_99",  # Identical photo ID!
        width=1280,
        height=720,
    )
    db.upsert_messages([msg1, msg2])

    # Act 1: Default Preset = KEEP_NEWEST
    groups = engine.find_duplicates(2, preset=RetentionPreset.KEEP_NEWEST)

    # Assert
    assert len(groups) == 1
    group = groups[0]
    assert group.group_type == DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION
    assert group.primary_message_id == 102
    assert group.diff_summary["has_update_marker"] is True

    candidates = db.get_deletion_candidates(2)
    assert len(candidates) == 1
    assert candidates[0].id == 101  # Old notice marked for deletion

    # Act 2: Switch Preset = KEEP_OLDEST
    engine.apply_preset(group, RetentionPreset.KEEP_OLDEST)
    candidates_oldest = db.get_deletion_candidates(2)
    assert len(candidates_oldest) == 1
    assert candidates_oldest[0].id == 102  # Newer marked for deletion

    # Act 3: Switch Preset = WHITELIST_ALL
    engine.apply_preset(group, RetentionPreset.WHITELIST_ALL)
    candidates_none = db.get_deletion_candidates(2)
    assert len(candidates_none) == 0  # Neither flagged for deletion


def test_fuzzy_near_duplicates(db, engine):
    # Arrange: Broadcast message with minor tag variations
    chat = ChatRecord(id=3, title="Broadcast Group")
    db.upsert_chat(chat)

    msg1 = MessageRecord(
        id=201,
        chat_id=3,
        date=datetime(2026, 3, 1, 10, 0),
        text="Important notice regarding server maintenance scheduled for Saturday 2 AM UTC #announcement",
        raw_text="Important notice regarding server maintenance scheduled for Saturday 2 AM UTC #announcement",
        text_hash=compute_text_hash(
            "Important notice regarding server maintenance scheduled for Saturday 2 AM UTC #announcement"
        ),
    )
    msg2 = MessageRecord(
        id=202,
        chat_id=3,
        date=datetime(2026, 3, 1, 10, 5),
        text="Important notice regarding server maintenance scheduled for Saturday 2 AM UTC #urgent #update",
        raw_text="Important notice regarding server maintenance scheduled for Saturday 2 AM UTC #urgent #update",
        text_hash=compute_text_hash(
            "Important notice regarding server maintenance scheduled for Saturday 2 AM UTC #urgent #update"
        ),
    )
    db.upsert_messages([msg1, msg2])

    # Act
    groups = engine.find_duplicates(3, preset=RetentionPreset.KEEP_NEWEST)

    # Assert
    assert len(groups) == 1
    group = groups[0]
    assert group.group_type == DuplicateGroupType.FUZZY_TEXT
    assert set(group.message_ids) == {201, 202}
