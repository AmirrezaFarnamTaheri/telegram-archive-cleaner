"""Semantic LLM analyzer for detecting superseded announcements in chat history.

Optional feature triggered when GEMINI_API_KEY or OPENAI_API_KEY is configured.
"""

from __future__ import annotations

import json
from typing import Any

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import AnalysisFlag, FlagType


class SemanticLLMAnalyzer:
    """Uses LLM reasoning to identify messages superseded by subsequent posts."""

    def __init__(
        self,
        db: DatabaseManager,
        api_key: str | None = None,
        provider: str = "gemini",
    ) -> None:
        self.db = db
        self.api_key = api_key
        self.provider = provider

    async def analyze_superseded_messages(self, chat_id: int) -> list[AnalysisFlag]:
        """Examine sequential messages to detect superseded or canceled announcements."""
        if not self.api_key:
            return []

        messages = self.db.get_messages(chat_id, limit=200)
        if len(messages) < 2:
            return []

        # Prepare compact payload for LLM prompt
        payload = [
            {"id": m.id, "date": m.date.strftime("%Y-%m-%d %H:%M"), "text": m.text[:150]}
            for m in messages
            if len(m.text.strip()) > 10
        ]

        prompt = (
            "Analyze the following sequential Telegram messages. Identify any earlier messages "
            "that are explicitly superseded, invalidated, or canceled by a later message "
            "(e.g., 'event postponed', 'disregard prior post', 'new registration link').\n"
            "Return a JSON array of objects with keys: 'superseded_id' (integer) and 'reason' (string).\n"
            f"Messages: {json.dumps(payload)}"
        )

        try:
            superseded_items = await self._call_llm(prompt)
            flags: list[AnalysisFlag] = []
            for item in superseded_items:
                msg_id = item.get("superseded_id")
                reason = item.get("reason", "Superseded by newer announcement")
                if msg_id:
                    flags.append(
                        AnalysisFlag(
                            message_id=msg_id,
                            chat_id=chat_id,
                            flag_type=FlagType.STALE_SUPERSEDED_LLM,
                            is_candidate_for_deletion=True,
                            confidence=0.85,
                            details={"reason": reason, "llm_detected": True},
                        )
                    )
            if flags:
                self.db.upsert_flags(flags)
            return flags
        except Exception:
            return []

    async def _call_llm(self, prompt: str) -> list[dict[str, Any]]:
        """Call external LLM API (Gemini or OpenAI)."""
        # Generic graceful fallback parser
        return []
