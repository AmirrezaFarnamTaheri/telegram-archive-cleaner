"""Policy restriction and dead stub auditor.

Detects messages flagged by Telegram for copyright (DMCA), TOS violations,
or orphaned posts sent by deleted user accounts.
"""

from __future__ import annotations

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import AnalysisFlag, FlagType


class PolicyAuditor:
    """Audits messages for Telegram policy restrictions and orphaned account status."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def audit_policy_restrictions(self, chat_id: int) -> list[AnalysisFlag]:
        """Flag all messages affected by policy restrictions or deleted senders."""
        messages = self.db.get_messages(chat_id)
        flags: list[AnalysisFlag] = []

        for msg in messages:
            # 1. Telegram Platform Restriction Reason (DMCA, regional blocks, TOS)
            if msg.restriction_reason:
                flags.append(
                    AnalysisFlag(
                        message_id=msg.id,
                        chat_id=msg.chat_id,
                        flag_type=FlagType.POLICY_RESTRICTED,
                        is_candidate_for_deletion=True,
                        confidence=1.0,
                        details={"restriction": msg.restriction_reason},
                    )
                )

            # 2. Deleted User Sender
            if msg.is_deleted_sender:
                flags.append(
                    AnalysisFlag(
                        message_id=msg.id,
                        chat_id=msg.chat_id,
                        flag_type=FlagType.POLICY_DELETED_ACCOUNT,
                        is_candidate_for_deletion=True,
                        confidence=1.0,
                        details={"sender_id": msg.sender_id},
                    )
                )

            # 3. Empty / Inaccessible Media Stub
            if msg.media_type and not msg.media_id and not msg.file_size:
                flags.append(
                    AnalysisFlag(
                        message_id=msg.id,
                        chat_id=msg.chat_id,
                        flag_type=FlagType.POLICY_EMPTY_MEDIA,
                        is_candidate_for_deletion=True,
                        confidence=1.0,
                        details={"media_type": msg.media_type},
                    )
                )

        if flags:
            self.db.upsert_flags(flags)
        return flags

    def audit_chat_policy(self, chat_id: int) -> list[AnalysisFlag]:
        """Alias for audit_policy_restrictions."""
        return self.audit_policy_restrictions(chat_id)
