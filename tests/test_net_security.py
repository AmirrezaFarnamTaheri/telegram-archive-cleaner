"""Tests for net_security module including SSRF protection and URL normalization."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tg_cleaner.analyzer.links import LinkHealthChecker
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.net_security import (
    guess_filename_from_url,
    is_private_ip,
    is_safe_public_url,
    normalize_url,
    sanitize_filename,
)


def test_is_private_ip():
    """Verify private and reserved IPv4 and IPv6 subnets are identified."""
    assert is_private_ip("127.0.0.1") is True
    assert is_private_ip("10.0.0.1") is True
    assert is_private_ip("192.168.1.1") is True
    assert is_private_ip("172.16.0.1") is True
    assert is_private_ip("169.254.169.254") is True  # Cloud metadata
    assert is_private_ip("100.64.0.1") is True  # Carrier-grade NAT
    assert is_private_ip("198.18.0.1") is True  # Benchmarking
    assert is_private_ip("192.0.2.1") is True  # TEST-NET-1
    assert is_private_ip("::1") is True  # IPv6 loopback
    assert is_private_ip("fe80::1") is True  # IPv6 link-local

    # Public IP addresses
    assert is_private_ip("8.8.8.8") is False
    assert is_private_ip("1.1.1.1") is False
    assert is_private_ip("93.184.216.34") is False


def test_normalize_url():
    """Verify cloud URL rewriting for direct downloads."""
    # Dropbox dl=1
    db_url = "https://www.dropbox.com/s/12345/file.png?raw=1"
    norm_db = normalize_url(db_url)
    assert "dl=1" in norm_db
    assert "raw" not in norm_db

    # GitHub blob to raw
    gh_url = "https://github.com/torvalds/linux/blob/master/README"
    norm_gh = normalize_url(gh_url)
    assert norm_gh == "https://raw.githubusercontent.com/torvalds/linux/master/README"

    # Google Drive export link
    drive_url = "https://drive.google.com/file/d/abcdef12345/view?usp=sharing"
    norm_drive = normalize_url(drive_url)
    assert "export=download" in norm_drive
    assert "id=abcdef12345" in norm_drive


def test_sanitize_filename():
    """Verify traversal characters and forbidden symbols are cleaned."""
    dirty = "../../../etc/passwd"
    clean = sanitize_filename(dirty)
    assert ".." not in clean
    assert "/" not in clean

    windows_dirty = "file:name?with*symbols<>.jpg"
    clean_win = sanitize_filename(windows_dirty)
    assert ":" not in clean_win
    assert "*" not in clean_win


def test_guess_filename():
    """Verify filename inference with mime extensions."""
    name1 = guess_filename_from_url("https://example.com/archive.zip")
    assert name1 == "archive.zip"

    name2 = guess_filename_from_url("https://example.com/download-image", "image/png")
    assert name2 == "download-image.png"


def test_is_safe_public_url():
    """Verify SSRF target blocking."""
    # Localhost / internal
    safe, reason = is_safe_public_url("http://127.0.0.1/admin")
    assert safe is False

    safe, reason = is_safe_public_url("http://localhost:8000")
    assert safe is False

    safe, reason = is_safe_public_url("http://metadata.google.internal/computeMetadata/v1")
    assert safe is False

    # Credentials
    safe, reason = is_safe_public_url("http://user:pass@example.com")
    assert safe is False


@pytest.mark.asyncio
async def test_link_checker_does_not_mark_blocked_private_url_dead(tmp_path: Path):
    """An SSRF-blocked probe is unknown, not evidence that a link is dead."""
    db = DatabaseManager(str(tmp_path / "links.db"))
    db.init_db()
    checker = LinkHealthChecker(db=db)
    http_client = AsyncMock()

    is_dead, reason = await checker._check_http_url(
        http_client,
        "http://127.0.0.1/private",
    )

    assert is_dead is False
    assert "Skipped unsafe target" in reason
    http_client.head.assert_not_called()
    http_client.get.assert_not_called()
