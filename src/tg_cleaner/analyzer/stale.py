"""Temporal decay and expired deadline analyzer.

Identifies messages that have exceeded user retention cutoffs or reference expired dates.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import AnalysisFlag, FlagType


class StaleContentAnalyzer:
    """Analyzes message age against retention thresholds."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def check_stale_messages(
        self, chat_id: int, max_age_days: int | None = None
    ) -> list[AnalysisFlag]:
        """Flag messages older than a specified day threshold."""
        if not max_age_days or max_age_days <= 0:
            return []

        messages = self.db.get_active_messages(chat_id)
        now = datetime.now(UTC).replace(tzinfo=None)
        cutoff_date = now - timedelta(days=max_age_days)

        flags: list[AnalysisFlag] = []
        for msg in messages:
            if msg.date < cutoff_date:
                age_days = (now - msg.date).days
                flags.append(
                    AnalysisFlag(
                        message_id=msg.id,
                        chat_id=msg.chat_id,
                        flag_type=FlagType.STALE_OUTDATED_TIME,
                        is_candidate_for_deletion=True,
                        confidence=1.0,
                        details={
                            "age_days": age_days,
                            "cutoff_days": max_age_days,
                            "date": msg.date.isoformat(),
                        },
                    )
                )

        if flags:
            self.db.upsert_flags(flags)
        return flags

    def audit_stale_content(
        self, chat_id: int, max_age_days: int | None = None
    ) -> list[AnalysisFlag]:
        """Alias for check_stale_messages."""
        return self.check_stale_messages(chat_id, max_age_days)
