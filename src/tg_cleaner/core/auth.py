"""Telegram MTProto authentication management.

Provides interactive and API-driven authentication workflows for Telethon.
"""

from __future__ import annotations

from typing import Any

import typer

from tg_cleaner.core.settings import settings


class TelegramAuthManager:
    """Manages Telegram MTProto client lifecycle and user authentication."""

    def __init__(self, session_name: str | None = None) -> None:
        self.session_name = session_name or settings.telegram_session_name
        self._client: Any | None = None

    def reset_client(self) -> None:
        """Reset cached client instance so updated credentials take effect."""
        self._client = None

    def get_client(self) -> Any:
        """Instantiate or retrieve TelegramClient with proxy configuration."""
        if self._client is not None:
            return self._client

        from telethon import TelegramClient

        if not settings.telegram_api_id or not settings.telegram_api_hash:
            raise ValueError(
                "Telegram API credentials missing. Please configure your API ID and API Hash from https://my.telegram.org in the settings modal or .env file."
            )

        proxy = settings.get_proxy_tuple()
        self._client = TelegramClient(
            self.session_name,
            settings.telegram_api_id,
            settings.telegram_api_hash,
            proxy=proxy,
            connection_retries=2,
            retry_delay=1,
            timeout=8,
        )
        return self._client

    async def is_authorized(self) -> bool:
        """Check whether the client session is currently authorized."""
        try:
            client = self.get_client()
            if not client.is_connected():
                await client.connect()
            return await client.is_user_authorized()
        except Exception:
            return False

    async def send_login_code(self, phone: str) -> str:
        """Request a verification login code for the given phone number."""
        client = self.get_client()
        if not client.is_connected():
            await client.connect()

        res = await client.send_code_request(phone)
        return res.phone_code_hash

    async def sign_in_with_code(
        self,
        phone: str,
        code: str,
        phone_code_hash: str,
        password: str | None = None,
    ) -> Any:
        """Complete sign-in using phone code and optional 2FA password."""
        from telethon.errors import SessionPasswordNeededError

        client = self.get_client()
        if not client.is_connected():
            await client.connect()

        try:
            user = await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            return user
        except SessionPasswordNeededError:
            if not password:
                raise ValueError("Two-step verification enabled: 2FA password required.") from None
            user = await client.sign_in(password=password)
            return user

    async def logout(self) -> None:
        """Log out and terminate current session."""
        client = self.get_client()
        if client.is_connected():
            await client.log_out()

    async def login_cli_interactive(self, phone: str | None = None) -> None:
        """Interactive terminal login flow."""
        target_phone = phone or settings.telegram_phone
        if not target_phone:
            target_phone = typer.prompt(
                "Enter your Telegram phone number (with country code, e.g. +1234567890)"
            )

        typer.echo(f"Requesting login code for {target_phone}...")
        phone_code_hash = await self.send_login_code(target_phone)

        code = typer.prompt("Enter the verification code sent to your Telegram app")

        try:
            user = await self.sign_in_with_code(target_phone, code, phone_code_hash)
        except ValueError as exc:
            if "2fa password required" not in str(exc).lower():
                raise
            password = typer.prompt(
                "Enter your 2FA Two-Step Verification Password", hide_input=True
            )
            user = await self.sign_in_with_code(
                target_phone, code, phone_code_hash, password=password
            )

        name = getattr(user, "first_name", "Telegram User")
        typer.secho(f"[OK] Successfully logged in as {name}!", fg=typer.colors.GREEN)
