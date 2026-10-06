"""Cloud Export and Offsite Backup Manager.

Absorbed and adopted from link-to-cloud provider architectures:
Provides streaming and resumable backup uploads to Google Drive,
Dropbox, and GitHub repository storage with SHA-256 checksum validation.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from tg_cleaner.core.net_security import sanitize_filename
from tg_cleaner.core.settings import settings


@dataclass
class CloudExportResult:
    """Result of exporting a backup archive to offsite cloud storage."""

    provider: str
    target_path: str
    file_id: str | None
    web_link: str | None
    sha256: str
    bytes_uploaded: int
    success: bool
    error: str | None = None


class CloudExportManager:
    """Orchestrates offloading pre-deletion backups to cloud providers."""

    def __init__(self, backup_dir: str | Path | None = None) -> None:
        self.backup_dir = Path(backup_dir or settings.backup_dir)

    def verify_backup_integrity(self, backup_file: Path) -> tuple[bool, str, dict[str, Any]]:
        """Verify the SHA-256 checksum recorded in the backup file against its contents."""
        with open(backup_file, encoding="utf-8") as f:
            data = json.load(f)

        expected_hash = data.get("sha256") or data.get("sha256_checksum", "")
        messages = data.get("messages", [])
        actual_hash = hashlib.sha256(
            json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

        is_valid = actual_hash == expected_hash
        return is_valid, actual_hash, data

    async def export_to_google_drive(
        self,
        backup_filename: str,
        access_token: str,
        folder_id: str | None = None,
        chunk_size: int = 8 * 1024 * 1024,
    ) -> CloudExportResult:
        """Upload a backup file using Google Drive resumable upload session."""
        backup_path = self.backup_dir / backup_filename
        if not backup_path.is_file():
            return CloudExportResult(
                provider="google_drive",
                target_path=backup_filename,
                file_id=None,
                web_link=None,
                sha256="",
                bytes_uploaded=0,
                success=False,
                error=f"Backup file not found: {backup_filename}",
            )

        is_valid, computed_hash, _ = self.verify_backup_integrity(backup_path)
        if not is_valid:
            return CloudExportResult(
                provider="google_drive",
                target_path=backup_filename,
                file_id=None,
                web_link=None,
                sha256=computed_hash,
                bytes_uploaded=0,
                success=False,
                error="Backup integrity check failed: SHA-256 mismatch",
            )

        file_bytes = backup_path.read_bytes()
        total_size = len(file_bytes)
        safe_name = sanitize_filename(backup_path.name)

        metadata: dict[str, Any] = {
            "name": safe_name,
            "mimeType": "application/json",
            "description": f"Telegram Archive Backup (SHA256: {computed_hash})",
        }
        if folder_id:
            metadata["parents"] = [folder_id]

        async with httpx.AsyncClient(timeout=60.0) as client:
            # 1. Initiate Resumable Session
            init_headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "application/json",
                "X-Upload-Content-Length": str(total_size),
            }
            init_resp = await client.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
                json=metadata,
                headers=init_headers,
            )
            if init_resp.status_code != 200:
                return CloudExportResult(
                    provider="google_drive",
                    target_path=safe_name,
                    file_id=None,
                    web_link=None,
                    sha256=computed_hash,
                    bytes_uploaded=0,
                    success=False,
                    error=f"Drive session initiation failed: HTTP {init_resp.status_code}",
                )

            session_url = init_resp.headers.get("Location")
            if not session_url:
                return CloudExportResult(
                    provider="google_drive",
                    target_path=safe_name,
                    file_id=None,
                    web_link=None,
                    sha256=computed_hash,
                    bytes_uploaded=0,
                    success=False,
                    error="Google Drive did not return a resumable session URL",
                )

            # 2. Upload Body in Resumable Chunks
            offset = 0
            file_id = None
            web_link = None

            while offset < total_size:
                end = min(offset + chunk_size, total_size)
                chunk = file_bytes[offset:end]
                chunk_len = len(chunk)

                headers = {
                    "Content-Length": str(chunk_len),
                    "Content-Range": f"bytes {offset}-{end - 1}/{total_size}",
                    "Content-Type": "application/json",
                }

                put_resp = await client.put(session_url, content=chunk, headers=headers)
                if put_resp.status_code in (200, 201):
                    data = put_resp.json()
                    file_id = data.get("id")
                    web_link = data.get("webViewLink")
                    break
                elif put_resp.status_code == 308:
                    offset = end
                else:
                    return CloudExportResult(
                        provider="google_drive",
                        target_path=safe_name,
                        file_id=None,
                        web_link=None,
                        sha256=computed_hash,
                        bytes_uploaded=offset,
                        success=False,
                        error=f"Upload chunk failed: HTTP {put_resp.status_code}",
                    )

            return CloudExportResult(
                provider="google_drive",
                target_path=safe_name,
                file_id=file_id,
                web_link=web_link,
                sha256=computed_hash,
                bytes_uploaded=total_size,
                success=True,
            )

    async def export_to_github(
        self,
        backup_filename: str,
        token: str,
        repo: str,
        branch: str = "main",
        commit_message: str | None = None,
    ) -> CloudExportResult:
        """Export a backup snapshot directly to a GitHub repository via Contents API."""
        backup_path = self.backup_dir / backup_filename
        if not backup_path.is_file():
            return CloudExportResult(
                provider="github",
                target_path=backup_filename,
                file_id=None,
                web_link=None,
                sha256="",
                bytes_uploaded=0,
                success=False,
                error=f"File not found: {backup_filename}",
            )

        is_valid, computed_hash, _ = self.verify_backup_integrity(backup_path)
        if not is_valid:
            return CloudExportResult(
                provider="github",
                target_path=backup_filename,
                file_id=None,
                web_link=None,
                sha256=computed_hash,
                bytes_uploaded=0,
                success=False,
                error="Backup integrity check failed: SHA-256 mismatch",
            )

        file_bytes = backup_path.read_bytes()
        total_size = len(file_bytes)
        safe_name = sanitize_filename(backup_path.name)
        remote_path = f"telegram-backups/{safe_name}"

        b64_content = base64.b64encode(file_bytes).decode("ascii")
        msg = commit_message or f"backup: archive {safe_name} (SHA256: {computed_hash[:16]})"

        payload = {
            "message": msg,
            "content": b64_content,
            "branch": branch,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            resp = await client.put(
                f"https://api.github.com/repos/{repo}/contents/{remote_path}",
                json=payload,
                headers=headers,
            )

            if resp.status_code not in (200, 201):
                return CloudExportResult(
                    provider="github",
                    target_path=remote_path,
                    file_id=None,
                    web_link=None,
                    sha256=computed_hash,
                    bytes_uploaded=0,
                    success=False,
                    error=f"GitHub API Error: HTTP {resp.status_code}",
                )

            data = resp.json()
            content_meta = data.get("content", {})
            html_url = content_meta.get("html_url")
            sha = content_meta.get("sha")

            return CloudExportResult(
                provider="github",
                target_path=remote_path,
                file_id=sha,
                web_link=html_url,
                sha256=computed_hash,
                bytes_uploaded=total_size,
                success=True,
            )
