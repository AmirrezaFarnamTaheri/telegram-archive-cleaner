"""Unit tests for LinkHealthChecker, StaleContentAnalyzer, PolicyAuditor, and LLM analyzer."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
import respx

from tg_cleaner.analyzer.links import LinkHealthChecker
from tg_cleaner.analyzer.policy import PolicyAuditor
from tg_cleaner.analyzer.stale import StaleContentAnalyzer
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import (
    ChatRecord,
    FlagType,
    MessageRecord,
)


@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "test_analyzers.db"
    manager = DatabaseManager(str(db_file))
    manager.init_db()
    return manager


@pytest.mark.asyncio
async def test_link_health_checker_http(db):
    # Arrange
    chat = ChatRecord(id=10, title="Link Chat")
    db.upsert_chat(chat)

    msg1 = MessageRecord(
        id=1,
        chat_id=10,
        date=datetime(2026, 1, 1),
        text="Check working site: https://healthy.example.com",
        raw_text="Check working site: https://healthy.example.com",
        has_links=True,
        extracted_urls=["https://healthy.example.com"],
    )
    msg2 = MessageRecord(
        id=2,
        chat_id=10,
        date=datetime(2026, 1, 2),
        text="Check dead site: https://dead.example.com/not-found",
        raw_text="Check dead site: https://dead.example.com/not-found",
        has_links=True,
        extracted_urls=["https://dead.example.com/not-found"],
    )
    db.upsert_messages([msg1, msg2])

    with respx.mock(assert_all_called=False) as respx_mock:
        respx_mock.head("https://healthy.example.com").respond(status_code=200)
        respx_mock.head("https://dead.example.com/not-found").respond(status_code=404)
        respx_mock.get("https://dead.example.com/not-found").respond(status_code=404)

        # Act
        checker = LinkHealthChecker(db)
        flags = await checker.check_links_in_chat(10)

        # Assert
        assert len(flags) == 1
        assert flags[0].message_id == 2
        assert flags[0].flag_type == FlagType.STALE_DEAD_LINK
        assert flags[0].is_candidate_for_deletion is True


@pytest.mark.asyncio
async def test_link_health_checker_telegram_invite(db):
    # Arrange: Telethon client returns invite expired error
    chat = ChatRecord(id=20, title="Invite Chat")
    db.upsert_chat(chat)

    msg = MessageRecord(
        id=50,
        chat_id=20,
        date=datetime(2026, 2, 1),
        text="Join our group: https://t.me/+ExpiredHash123",
        raw_text="Join our group: https://t.me/+ExpiredHash123",
        has_links=True,
        extracted_urls=["https://t.me/+ExpiredHash123"],
    )
    db.upsert_messages([msg])

    from telethon.errors import InviteHashExpiredError

    mock_client = AsyncMock()
    mock_client.side_effect = InviteHashExpiredError(request=None)

    # Act
    checker = LinkHealthChecker(db, client=mock_client)
    flags = await checker.check_links_in_chat(20)

    # Assert
    assert len(flags) == 1
    assert flags[0].message_id == 50
    assert flags[0].flag_type == FlagType.STALE_EXPIRED_INVITE


def test_stale_content_analyzer_time_cutoff(db):
    # Arrange
    chat = ChatRecord(id=30, title="Stale Chat")
    db.upsert_chat(chat)

    old_date = datetime.utcnow() - timedelta(days=200)
    recent_date = datetime.utcnow() - timedelta(days=10)

    msg_old = MessageRecord(
        id=301,
        chat_id=30,
        date=old_date,
        text="Old message from last year",
        raw_text="Old message from last year",
    )
    msg_recent = MessageRecord(
        id=302,
        chat_id=30,
        date=recent_date,
        text="Recent update message",
        raw_text="Recent update message",
    )
    db.upsert_messages([msg_old, msg_recent])

    # Act
    analyzer = StaleContentAnalyzer(db)
    flags = analyzer.check_stale_messages(30, max_age_days=90)

    # Assert
    assert len(flags) == 1
    assert flags[0].message_id == 301
    assert flags[0].flag_type == FlagType.STALE_OUTDATED_TIME


def test_policy_auditor(db):
    # Arrange
    chat = ChatRecord(id=40, title="Policy Audit Chat")
    db.upsert_chat(chat)

    msg_restricted = MessageRecord(
        id=401,
        chat_id=40,
        date=datetime(2026, 3, 1),
        text="Post flagged for copyright",
        raw_text="Post flagged for copyright",
        restriction_reason="[RestrictionReason(platform='all', reason='dmca', text='Copyrighted material')]",
    )
    msg_deleted_user = MessageRecord(
        id=402,
        chat_id=40,
        date=datetime(2026, 3, 2),
        text="Message from deleted account",
        raw_text="Message from deleted account",
        is_deleted_sender=True,
    )
    msg_normal = MessageRecord(
        id=403,
        chat_id=40,
        date=datetime(2026, 3, 3),
        text="Standard clean message",
        raw_text="Standard clean message",
    )
    db.upsert_messages([msg_restricted, msg_deleted_user, msg_normal])

    # Act
    auditor = PolicyAuditor(db)
    flags = auditor.audit_policy_restrictions(40)

    # Assert
    assert len(flags) == 2
    flag_types = {f.flag_type for f in flags}
    assert FlagType.POLICY_RESTRICTED in flag_types
    assert FlagType.POLICY_DELETED_ACCOUNT in flag_types
