"""Application settings managed by Pydantic Settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for Telegram Archive Cleaner."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Telegram MTProto Credentials
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_phone: str | None = None
    telegram_session_name: str = "cleaner_session"

    # Telegram Proxy / Relay Configuration
    telegram_proxy_type: str | None = None  # "socks5", "http", "mtproxy"
    telegram_proxy_host: str | None = None
    telegram_proxy_port: int | None = None
    telegram_proxy_username: str | None = None
    telegram_proxy_password: str | None = None
    telegram_proxy_secret: str | None = None

    # Performance & Data Saver Mode
    data_saver_mode: bool = True

    # External Edge Relay (Cloudflare Worker, Railway, etc.)
    # Offloads dead-link checks and remote fetches to save local network bandwidth
    relay_url: str | None = None
    relay_shared_secret: str | None = None

    # Storage Paths
    db_path: str = "data/cleaner.db"
    backup_dir: str = "backups"

    # Web Dashboard Server
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    api_token: str | None = None
    max_import_bytes: int = 64 * 1024 * 1024
    stale_after_days: int | None = None
    enable_demo_data: bool = True

    # Optional Semantic LLM Evaluation (explicit opt-in; message text leaves the device)
    enable_llm_analysis: bool = False
    llm_provider: str = "gemini"
    llm_model: str | None = None
    gemini_api_key: str | None = None
    openai_api_key: str | None = None

    @field_validator("telegram_api_id", "telegram_proxy_port", "web_port", "max_import_bytes", "stale_after_days", mode="before")
    @classmethod
    def parse_empty_int(cls, v: Any) -> int | None:
        if v is None or v == "":
            return None
        return int(v)

    @field_validator(
        "telegram_api_hash",
        "telegram_phone",
        "telegram_proxy_type",
        "telegram_proxy_host",
        "telegram_proxy_username",
        "telegram_proxy_password",
        "telegram_proxy_secret",
        "relay_url",
        "relay_shared_secret",
        "api_token",
        "gemini_api_key",
        "openai_api_key",
        "llm_model",
        mode="before",
    )
    @classmethod
    def parse_empty_str(cls, v: Any) -> str | None:
        if v is None:
            return None
        cleaned = str(v).strip()
        return cleaned if cleaned else None

    def get_proxy_tuple(self) -> tuple | None:
        """Construct proxy tuple for Telethon if configured."""
        if (
            not self.telegram_proxy_type
            or not self.telegram_proxy_host
            or not self.telegram_proxy_port
        ):
            return None

        match self.telegram_proxy_type.lower():
            case "socks5":
                return (
                    "socks5",
                    self.telegram_proxy_host,
                    self.telegram_proxy_port,
                    True,
                    self.telegram_proxy_username,
                    self.telegram_proxy_password,
                )
            case "http":
                return (
                    "http",
                    self.telegram_proxy_host,
                    self.telegram_proxy_port,
                    True,
                    self.telegram_proxy_username,
                    self.telegram_proxy_password,
                )
            case "mtproxy":
                return (
                    "mtproxy",
                    self.telegram_proxy_host,
                    self.telegram_proxy_port,
                    self.telegram_proxy_secret,
                )
            case _:
                return None


# Global singleton instance
settings = Settings()


def update_credentials_and_save(
    api_id: int | None = None,
    api_hash: str | None = None,
    phone: str | None = None,
    proxy_type: str | None = None,
    proxy_host: str | None = None,
    proxy_port: int | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    proxy_secret: str | None = None,
    env_path: str = ".env",
) -> None:
    """Update settings in memory and persist updated values to .env file."""
    if api_id is not None:
        settings.telegram_api_id = int(api_id) if api_id else None
    if api_hash is not None:
        settings.telegram_api_hash = str(api_hash).strip() if api_hash else None
    if phone is not None:
        settings.telegram_phone = str(phone).strip() if phone else None
    if proxy_type is not None:
        settings.telegram_proxy_type = str(proxy_type).strip() if proxy_type else None
    if proxy_host is not None:
        settings.telegram_proxy_host = str(proxy_host).strip() if proxy_host else None
    if proxy_port is not None:
        settings.telegram_proxy_port = int(proxy_port) if proxy_port else None
    if proxy_username is not None:
        settings.telegram_proxy_username = str(proxy_username).strip() if proxy_username else None
    if proxy_password is not None:
        settings.telegram_proxy_password = str(proxy_password).strip() if proxy_password else None
    if proxy_secret is not None:
        settings.telegram_proxy_secret = str(proxy_secret).strip() if proxy_secret else None

    env_file = Path(env_path)
    existing_lines: list[str] = []
    if env_file.exists():
        existing_lines = env_file.read_text(encoding="utf-8").splitlines()
    elif Path(".env.example").exists():
        existing_lines = Path(".env.example").read_text(encoding="utf-8").splitlines()

    updates: dict[str, str] = {}
    if api_id is not None:
        updates["TELEGRAM_API_ID"] = str(api_id) if api_id else ""
    if api_hash is not None:
        updates["TELEGRAM_API_HASH"] = str(api_hash).strip() if api_hash else ""
    if phone is not None:
        updates["TELEGRAM_PHONE"] = str(phone).strip() if phone else ""
    if proxy_type is not None:
        updates["TELEGRAM_PROXY_TYPE"] = str(proxy_type).strip() if proxy_type else ""
    if proxy_host is not None:
        updates["TELEGRAM_PROXY_HOST"] = str(proxy_host).strip() if proxy_host else ""
    if proxy_port is not None:
        updates["TELEGRAM_PROXY_PORT"] = str(proxy_port) if proxy_port else ""
    if proxy_username is not None:
        updates["TELEGRAM_PROXY_USERNAME"] = str(proxy_username).strip() if proxy_username else ""
    if proxy_password is not None:
        updates["TELEGRAM_PROXY_PASSWORD"] = str(proxy_password).strip() if proxy_password else ""
    if proxy_secret is not None:
        updates["TELEGRAM_PROXY_SECRET"] = str(proxy_secret).strip() if proxy_secret else ""

    new_lines: list[str] = []
    seen: set[str] = set()

    for line in existing_lines:
        trimmed = line.strip()
        matched_key = None
        for k in updates:
            if trimmed.startswith(f"{k}=") or trimmed.startswith(f"# {k}="):
                matched_key = k
                break
        if matched_key:
            new_lines.append(f"{matched_key}={updates[matched_key]}")
            seen.add(matched_key)
        else:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in seen:
            new_lines.append(f"{k}={v}")

    env_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = env_file.with_name(f".{env_file.name}.tmp")
    tmp_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp_file, 0o600)
    except OSError:
        pass
    os.replace(tmp_file, env_file)
    try:
        os.chmod(env_file, 0o600)
    except OSError:
        pass
