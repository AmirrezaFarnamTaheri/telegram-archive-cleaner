"""Async link health checker for external web URLs and Telegram invite links.

Part of the Application (Use Case) Layer.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import AnalysisFlag, FlagType, MessageRecord
from tg_cleaner.core.net_security import is_safe_public_url, normalize_url
from tg_cleaner.core.settings import settings

_TG_INVITE_REGEX = re.compile(r"t\.me/(?:\+|joinchat/)([a-zA-Z0-9_\-]+)", re.IGNORECASE)


class LinkHealthChecker:
    """Asynchronously audits links in chat messages for 404s, DNS failures, and expired invites."""

    def __init__(self, db: DatabaseManager, client: Any | None = None) -> None:
        self.db = db
        self.client = client

    async def check_links_in_chat(
        self, chat_id: int, concurrency: int = 5, timeout: float = 3.0
    ) -> list[AnalysisFlag]:
        """Scan all messages with links and flag dead or expired URLs."""
        messages = self.db.get_messages(chat_id)
        messages_with_links = [m for m in messages if m.has_links and m.extracted_urls]
        if not messages_with_links:
            return []

        semaphore = asyncio.Semaphore(concurrency)
        flags: list[AnalysisFlag] = []

        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        ) as http_client:
            tasks = [
                self._audit_message_links(m, http_client, semaphore) for m in messages_with_links
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for res in results:
                if isinstance(res, list):
                    flags.extend(res)

        if flags:
            self.db.upsert_flags(flags)
        return flags

    async def _audit_message_links(
        self,
        message: MessageRecord,
        http_client: httpx.AsyncClient,
        semaphore: asyncio.Semaphore,
    ) -> list[AnalysisFlag]:
        """Check all links extracted from a single message."""
        message_flags: list[AnalysisFlag] = []

        for url in message.extracted_urls:
            invite_match = _TG_INVITE_REGEX.search(url)
            if invite_match:
                # Telegram Invite link check
                invite_hash = invite_match.group(1)
                is_expired, reason = await self._check_telegram_invite(invite_hash)
                if is_expired:
                    message_flags.append(
                        AnalysisFlag(
                            message_id=message.id,
                            chat_id=message.chat_id,
                            flag_type=FlagType.STALE_EXPIRED_INVITE,
                            is_candidate_for_deletion=True,
                            confidence=1.0,
                            details={"url": url, "reason": reason},
                        )
                    )
            else:
                # Standard HTTP / HTTPS URL check
                async with semaphore:
                    is_dead, reason = await self._check_http_url(http_client, url)
                    if is_dead:
                        message_flags.append(
                            AnalysisFlag(
                                message_id=message.id,
                                chat_id=message.chat_id,
                                flag_type=FlagType.STALE_DEAD_LINK,
                                is_candidate_for_deletion=True,
                                confidence=1.0,
                                details={"url": url, "reason": reason},
                            )
                        )
        return message_flags

    async def _check_http_url(self, http_client: httpx.AsyncClient, url: str) -> tuple[bool, str]:
        """Probe an external URL via edge relay or direct SSRF-safe request."""
        clean_url = normalize_url(url)

        # 1. Edge Relay Offloading (Cloudflare Worker, Railway, etc.)
        if settings.relay_url and settings.relay_shared_secret:
            relay_endpoint = settings.relay_url.rstrip("/")
            if not relay_endpoint.endswith("/relay"):
                relay_endpoint = f"{relay_endpoint}/relay"
            try:
                resp = await http_client.post(
                    relay_endpoint,
                    json={"url": clean_url, "method": "HEAD"},
                    headers={
                        "Authorization": f"Bearer {settings.relay_shared_secret}",
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code in (404, 410):
                    return True, f"Edge Relay: HTTP {resp.status_code} Not Found/Gone"
                if resp.status_code >= 500:
                    return True, f"Edge Relay: HTTP {resp.status_code} Failure"
                return False, "OK (via Edge Relay)"
            except Exception as e:
                return False, f"Edge relay unreachable: {e}"

        # 2. SSRF Protection on Direct Local Network Requests
        is_safe, reason = is_safe_public_url(clean_url)
        if not is_safe:
            if "DNS resolution failure" in reason or "Could not resolve" in reason:
                return True, "DNS Resolution Failure"
            return True, f"Blocked unsafe target: {reason}"

        # 3. Direct Request
        try:
            resp = await http_client.head(clean_url)
            if resp.status_code == 405:  # Method Not Allowed on HEAD, retry GET
                resp = await http_client.get(clean_url)

            if resp.status_code in (404, 410):
                return True, f"HTTP {resp.status_code} Not Found/Gone"
            if resp.status_code >= 500:
                return True, f"HTTP {resp.status_code} Server Error"
            return False, "OK"
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return True, "Connection/DNS Failure"
        except Exception as e:
            return False, str(e)

    async def _check_telegram_invite(self, invite_hash: str) -> tuple[bool, str]:
        """Validate Telegram invite link without joining chat."""
        if not self.client:
            return False, "Telethon client not configured"

        try:
            from telethon.tl.functions.messages import CheckChatInviteRequest

            # In testing or production, invoke client
            if callable(self.client):
                await self.client(CheckChatInviteRequest(invite_hash))
            return False, "Valid"
        except Exception as e:
            err_name = type(e).__name__
            if "InviteHashExpired" in err_name or "InviteHashInvalid" in err_name:
                return True, f"Telegram invite {err_name}"
            return False, str(e)
