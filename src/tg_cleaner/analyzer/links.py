"""Check links without treating blocked or uncertain requests as dead links."""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import AnalysisFlag, FlagType, MessageRecord
from tg_cleaner.core.net_security import is_safe_public_url, normalize_url
from tg_cleaner.core.settings import settings

_TG_INVITE_REGEX = re.compile(r"t\.me/(?:\+|joinchat/)([a-zA-Z0-9_\-]+)", re.IGNORECASE)
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


class LinkHealthChecker:
    """Audit links, treating only definitive 404/410 responses as dead."""

    def __init__(self, db: DatabaseManager, client: Any | None = None) -> None:
        self.db = db
        self.client = client

    async def check_links_in_chat(
        self, chat_id: int, concurrency: int = 5, timeout: float = 3.0
    ) -> list[AnalysisFlag]:
        """Scan active messages with links and flag definitive dead/expired targets."""
        messages = self.db.get_active_messages(chat_id)
        messages_with_links = [m for m in messages if m.has_links and m.extracted_urls]
        if not messages_with_links:
            return []

        semaphore = asyncio.Semaphore(max(1, min(concurrency, 32)))
        flags: list[AnalysisFlag] = []
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": "TelegramArchiveCleaner/1.0 link-audit"},
        ) as http_client:
            results = await asyncio.gather(
                *(
                    self._audit_message_links(m, http_client, semaphore)
                    for m in messages_with_links
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, list):
                    flags.extend(result)

        if flags:
            self.db.upsert_flags(flags)
        return flags

    async def _audit_message_links(
        self,
        message: MessageRecord,
        http_client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> list[AnalysisFlag]:
        message_flags: list[AnalysisFlag] = []
        for url in message.extracted_urls:
            invite_match = _TG_INVITE_REGEX.search(url)
            if invite_match:
                expired, reason = await self._check_telegram_invite(invite_match.group(1))
                if expired:
                    message_flags.append(
                        AnalysisFlag(
                            message_id=message.id,
                            chat_id=message.chat_id,
                            flag_type=FlagType.STALE_EXPIRED_INVITE,
                            is_candidate_for_deletion=True,
                            confidence=1.0,
                            details={"url": url, "reason": reason, "evidence": "definitive"},
                        )
                    )
                continue

            async with semaphore:
                dead, reason = await self._check_http_url(http_client, url)
            if dead:
                message_flags.append(
                    AnalysisFlag(
                        message_id=message.id,
                        chat_id=message.chat_id,
                        flag_type=FlagType.STALE_DEAD_LINK,
                        is_candidate_for_deletion=True,
                        confidence=1.0,
                        details={"url": url, "reason": reason, "evidence": "definitive"},
                    )
                )
        return message_flags

    async def _check_http_url(self, http_client: httpx.AsyncClient, url: str) -> tuple[bool, str]:
        """Probe a URL and keep blocked or uncertain results separate from confirmed failures."""
        clean_url = normalize_url(url)

        if settings.relay_url and settings.relay_shared_secret:
            relay_endpoint = settings.relay_url.rstrip("/")
            if not relay_endpoint.endswith("/relay"):
                relay_endpoint = f"{relay_endpoint}/relay"
            try:
                response = await http_client.post(
                    relay_endpoint,
                    json={"url": clean_url, "method": "HEAD"},
                    headers={
                        "Authorization": f"Bearer {settings.relay_shared_secret}",
                        "Content-Type": "application/json",
                    },
                )
                if response.status_code in (404, 410):
                    return True, f"Edge relay: HTTP {response.status_code}"
                if response.status_code >= 400:
                    return False, f"Edge relay returned non-definitive HTTP {response.status_code}"
                return False, "OK (via edge relay)"
            except httpx.HTTPError as exc:
                return False, f"Edge relay unavailable: {type(exc).__name__}"
            except Exception as exc:
                return False, f"Edge relay unavailable: {type(exc).__name__}"

        current = clean_url
        for redirect_count in range(_MAX_REDIRECTS + 1):
            safe, reason = is_safe_public_url(current)
            if not safe:
                return False, f"Skipped unsafe target: {reason}"
            try:
                response = await http_client.head(current)
                if response.status_code == 405:
                    response = await http_client.get(current)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
                return False, "Transient connection/DNS/timeout failure"
            except httpx.HTTPError as exc:
                return False, f"HTTP probe failed: {type(exc).__name__}"
            except Exception as exc:
                return False, f"Probe failed: {type(exc).__name__}"

            if response.status_code in (404, 410):
                return True, f"HTTP {response.status_code} Not Found/Gone"
            if response.status_code in _REDIRECT_CODES:
                location = response.headers.get("location")
                if not location:
                    return False, f"HTTP {response.status_code} redirect without Location"
                if redirect_count >= _MAX_REDIRECTS:
                    return False, "Redirect limit exceeded"
                current = urljoin(current, location)
                continue
            if response.status_code >= 500 or response.status_code in (408, 425, 429):
                return False, f"Transient HTTP {response.status_code}"
            return False, f"Reachable HTTP {response.status_code}"

        return False, "Redirect limit exceeded"

    async def _check_telegram_invite(self, invite_hash: str) -> tuple[bool, str]:
        """Validate a Telegram invite without joining; only explicit invalid/expired errors count."""
        if not self.client:
            return False, "Telethon client not configured"
        try:
            from telethon.tl.functions.messages import CheckChatInviteRequest

            if callable(self.client):
                await self.client(CheckChatInviteRequest(invite_hash))
            return False, "Valid"
        except Exception as exc:
            err_name = type(exc).__name__
            if "InviteHashExpired" in err_name or "InviteHashInvalid" in err_name:
                return True, f"Telegram invite {err_name}"
            return False, f"Invite check inconclusive: {err_name}"
