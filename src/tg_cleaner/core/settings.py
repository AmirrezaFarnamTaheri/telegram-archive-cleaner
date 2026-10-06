"""Application settings managed by Pydantic Settings."""

from __future__ import annotations

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
    web_host: str = "0.0.0.0"
    web_port: int = 8000
    api_token: str | None = None

    # Optional Semantic LLM Evaluation
    gemini_api_key: str | None = None
    openai_api_key: str | None = None

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
