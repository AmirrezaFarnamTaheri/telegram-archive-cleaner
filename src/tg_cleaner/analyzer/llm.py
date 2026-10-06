"""Optional external semantic reviewer for superseded announcements.

This feature is deliberately opt-in because it sends selected message text to an external
provider. LLM output always requires manual approval before a message can be staged
for deletion.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import AnalysisFlag, FlagType

_DEFAULT_MODELS = {
    "gemini": "gemini-3.6-flash",
    "openai": "gpt-5.5",
}


class SemanticLLMAnalyzer:
    """Use an external LLM to identify explicitly superseded earlier messages."""

    def __init__(
        self,
        db: DatabaseManager,
        api_key: str | None = None,
        provider: str = "gemini",
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.db = db
        self.api_key = api_key
        self.provider = provider.strip().lower()
        self.model = model or _DEFAULT_MODELS.get(self.provider)
        self.timeout = timeout
        self.last_error: str | None = None

    async def analyze_superseded_messages(self, chat_id: int) -> list[AnalysisFlag]:
        """Detect supersession claims, validating every returned id against local input."""
        self.last_error = None
        if not self.api_key or not self.model:
            return []

        messages = self.db.get_active_messages(chat_id, limit=200)
        payload = [
            {
                "id": m.id,
                "date": m.date.isoformat(timespec="minutes"),
                "text": m.text[:500],
            }
            for m in messages
            if len(m.text.strip()) > 10
        ]
        if len(payload) < 2:
            return []

        valid_ids = {item["id"] for item in payload}
        prompt = (
            "Review these chronological Telegram messages. Return only messages for which a later "
            "message explicitly invalidates, cancels, replaces, reschedules, or supersedes the earlier "
            "message. Similarity alone is not supersession. Do not infer intent. Return JSON only as "
            "an array of objects with integer superseded_id and short reason.\n\n"
            f"Messages: {json.dumps(payload, ensure_ascii=False)}"
        )

        try:
            items = await self._call_llm(prompt)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return []

        flags: list[AnalysisFlag] = []
        seen: set[int] = set()
        for item in items:
            try:
                msg_id = int(item.get("superseded_id"))
            except (TypeError, ValueError):
                continue
            if msg_id not in valid_ids or msg_id in seen:
                continue
            seen.add(msg_id)
            reason = str(item.get("reason") or "Explicitly superseded by a later message")[:500]
            flags.append(
                AnalysisFlag(
                    message_id=msg_id,
                    chat_id=chat_id,
                    flag_type=FlagType.STALE_SUPERSEDED_LLM,
                    is_candidate_for_deletion=False,
                    confidence=0.65,
                    details={
                        "reason": reason,
                        "llm_detected": True,
                        "provider": self.provider,
                        "model": self.model,
                        "requires_review": True,
                    },
                )
            )
        if flags:
            self.db.upsert_flags(flags)
        return flags

    async def _call_llm(self, prompt: str) -> list[dict[str, Any]]:
        if self.provider == "openai":
            return await self._call_openai(prompt)
        if self.provider == "gemini":
            return await self._call_gemini(prompt)
        raise ValueError(f"Unsupported LLM provider: {self.provider}")

    async def _call_openai(self, prompt: str) -> list[dict[str, Any]]:
        payload = {
            "model": self.model,
            "input": [{"role": "user", "content": prompt}],
            "store": False,
            "max_output_tokens": 1200,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        chunks: list[str] = []
        for output in data.get("output", []):
            if output.get("type") != "message":
                continue
            for part in output.get("content", []):
                if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                    chunks.append(part["text"])
        return self._parse_json_array("\n".join(chunks))

    async def _call_gemini(self, prompt: str) -> list[dict[str, Any]]:
        schema = {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "superseded_id": {"type": "INTEGER"},
                    "reason": {"type": "STRING"},
                },
                "required": ["superseded_id", "reason"],
            },
        }
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": str(self.api_key), "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return []
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "\n".join(str(part.get("text", "")) for part in parts if part.get("text"))
        return self._parse_json_array(text)

    @staticmethod
    def _parse_json_array(text: str) -> list[dict[str, Any]]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        parsed = json.loads(cleaned or "[]")
        if not isinstance(parsed, list):
            raise ValueError("LLM response was not a JSON array")
        return [item for item in parsed if isinstance(item, dict)]
