"""End-to-end integration test verifying complete audit and cleanup lifecycle.

Covers:
1. Telegram Desktop export import
2. Multi-engine analysis (dedupe, same media diff caption, link health, policy)
3. Retention preset updates and dynamic candidate re-evaluation
4. Verified JSON backup creation with SHA-256 check
5. Paced deletion simulation and local DB synchronization
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tg_cleaner.analyzer.dedupe import DeduplicationEngine
from tg_cleaner.analyzer.policy import PolicyAuditor
from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.cleaner.executor import DeletionExecutor
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import (
    DuplicateGroupType,
    FlagType,
    RetentionPreset,
)
from tg_cleaner.ingest.desktop_export import import_desktop_export_from_dict


@pytest.mark.asyncio
async def test_complete_cleaner_lifecycle(tmp_path: Path):
    """Verify full end-to-end flow from raw export ingestion to verified deletion."""
    db_file = tmp_path / "lifecycle.db"
    backup_dir = tmp_path / "lifecycle_backups"

    db = DatabaseManager(str(db_file))
    db.init_db()

    # Step 1: Ingest raw Telegram Desktop JSON export
    export_payload = {
        "name": "Community Archive",
        "type": "supergroup",
        "id": 777,
        "messages": [
            # Exact duplicate pair
            {
                "id": 1,
                "type": "message",
                "date": "2026-01-01T10:00:00",
                "text": "Exact duplicate text announcement",
            },
            {
                "id": 2,
                "type": "message",
                "date": "2026-01-01T10:05:00",
                "text": "Exact duplicate text announcement",
            },
            # Same media, different captions
            {
                "id": 3,
                "type": "message",
                "date": "2026-01-02T10:00:00",
                "text": "Initial short announcement",
                "media_type": "photo",
                "file": "photo_poster_123.jpg",
                "width": 1280,
                "height": 720,
            },
            {
                "id": 4,
                "type": "message",
                "date": "2026-01-02T12:00:00",
                "text": "Updated detailed announcement with extensive notes and links #update",
                "media_type": "photo",
                "file": "photo_poster_123.jpg",
                "width": 1280,
                "height": 720,
            },
            # Policy restricted stub
            {
                "id": 5,
                "type": "message",
                "date": "2026-01-03T10:00:00",
                "text": "Blocked media",
                "media_type": "video",
                # missing file & size -> empty media stub
            },
        ],
    }

    chat, messages = import_desktop_export_from_dict(export_payload, db)
    assert chat.id == 777
    assert len(messages) == 5

    # Step 2: Run Multi-Engine Audit Pipeline
    dedupe_engine = DeduplicationEngine(db)
    dedupe_groups = dedupe_engine.detect_duplicates_in_chat(chat.id)
    assert len(dedupe_groups) == 2  # 1 exact text group, 1 same media diff caption group

    policy_auditor = PolicyAuditor(db)
    policy_flags = policy_auditor.audit_policy_restrictions(chat.id)
    assert len(policy_flags) == 1
    assert policy_flags[0].flag_type == FlagType.POLICY_EMPTY_MEDIA

    # Verify initial stats
    stats = db.get_scan_stats(chat.id)
    assert stats.total_messages == 5
    assert stats.exact_duplicates == 2
    assert stats.same_media_diff_caption == 2
    assert stats.policy_restricted == 1

    # In default KEEP_NEWEST preset:
    # Exact duplicate msg1 is candidate (msg2 is newest keeper)
    # Same media msg3 is candidate (msg4 is newest keeper)
    # Policy msg5 is candidate
    candidates = db.get_deletion_candidates(chat.id)
    cand_ids = {m.id for m in candidates}
    assert 1 in cand_ids  # older exact text
    assert 3 in cand_ids  # older photo caption
    assert 5 in cand_ids  # empty media stub
    assert 2 not in cand_ids  # kept
    assert 4 not in cand_ids  # kept

    # Step 3: Test Dynamic Preset Switching
    # Locate same media diff caption group
    same_media_group = next(
        g for g in dedupe_groups if g.group_type == DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION
    )
    # Switch to KEEP_OLDEST: msg3 is now kept, msg4 becomes candidate
    updated_flags = dedupe_engine.apply_retention_preset(
        same_media_group, RetentionPreset.KEEP_OLDEST
    )
    assert len(updated_flags) == 2

    candidates_after_switch = db.get_deletion_candidates(chat.id)
    cand_ids_after = {m.id for m in candidates_after_switch}
    assert 3 not in cand_ids_after  # msg3 is now keeper
    assert 4 in cand_ids_after  # msg4 is now candidate

    # Switch to WHITELIST_ALL: neither msg3 nor msg4 is candidate
    dedupe_engine.apply_retention_preset(same_media_group, RetentionPreset.WHITELIST_ALL)
    cand_ids_whitelist = {m.id for m in db.get_deletion_candidates(chat.id)}
    assert 3 not in cand_ids_whitelist
    assert 4 not in cand_ids_whitelist

    # Switch back to KEEP_LONGEST: msg4 has longer text, so msg3 is candidate
    dedupe_engine.apply_retention_preset(same_media_group, RetentionPreset.KEEP_LONGEST)
    final_candidates = db.get_deletion_candidates(chat.id)
    final_cand_ids = [m.id for m in final_candidates]
    assert 3 in final_cand_ids
    assert 4 not in final_cand_ids

    # Step 4: Pre-Deletion Backup & Paced Deletion Execution
    backup_mgr = BackupManager(str(backup_dir))
    mock_client = AsyncMock()

    executor = DeletionExecutor(
        db=db,
        client=mock_client,
        backup_manager=backup_mgr,
        min_delay=0.01,
        max_delay=0.02,
    )

    # Execute paced live deletion
    deletion_result = await executor.delete_candidates(
        chat_id=chat.id,
        message_ids=final_cand_ids,
        dry_run=False,
    )

    assert deletion_result.deleted_count == len(final_cand_ids)
    assert Path(deletion_result.backup_file).is_file()
    assert backup_mgr.verify_backup(deletion_result.backup_file) is True
    assert mock_client.delete_messages.called

    # Step 5: Verify Local Database Synchronization
    remaining_messages = [m for m in db.get_messages(chat.id) if not m.is_deleted_locally]
    remaining_ids = {m.id for m in remaining_messages}
    # Remaining should be msg2 (kept exact duplicate) and msg4 (kept richest announcement)
    assert remaining_ids == {2, 4}

    # Verify backup recorded in database
    backups = db.list_backups(chat.id)
    assert len(backups) == 1
    assert backups[0]["message_count"] == len(final_cand_ids)
