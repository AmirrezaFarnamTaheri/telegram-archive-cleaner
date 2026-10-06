"""REST API routes for Telegram Archive Cleaner dashboard."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tg_cleaner.analyzer.dedupe import DeduplicationEngine
from tg_cleaner.analyzer.links import LinkHealthChecker
from tg_cleaner.analyzer.policy import PolicyAuditor
from tg_cleaner.analyzer.stale import StaleContentAnalyzer
from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.cleaner.executor import DeletionExecutor, DeletionResult
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import (
    ChatRecord,
    MessageRecord,
    RetentionPreset,
    ScanStats,
)
from tg_cleaner.core.net_security import sanitize_filename
from tg_cleaner.ingest.desktop_export import import_desktop_export_from_dict

router = APIRouter(prefix="/api", tags=["cleaner"])


class PresetUpdateRequest(BaseModel):
    """Payload to update retention preset for a duplicate group."""

    preset: RetentionPreset


class DeleteRequest(BaseModel):
    """Payload to delete flagged messages."""

    message_ids: list[int]
    dry_run: bool = True


class ScanResponse(BaseModel):
    """Scan completion response."""

    chat_id: int
    flags_generated: int
    stats: ScanStats


class CloudExportRequest(BaseModel):
    """Payload to export a backup snapshot to cloud storage."""

    provider: str = "github"
    token: str
    repo: str | None = None
    branch: str = "main"
    folder_id: str | None = None


@router.get("/health")
def get_health(request: Request) -> dict[str, Any]:
    """Health check endpoint checking database integrity."""
    db: DatabaseManager = request.app.state.db
    is_healthy = db.is_healthy()
    return {"status": "healthy" if is_healthy else "unhealthy", "db_healthy": is_healthy}


@router.get("/chats", response_model=list[ChatRecord])
def list_chats(request: Request) -> list[ChatRecord]:
    """List all registered chats."""
    db: DatabaseManager = request.app.state.db
    return db.list_chats()


@router.post("/demo/generate")
def generate_demo_chat(request: Request) -> dict[str, Any]:
    """Populate database with rich demonstration dataset containing all duplicate & stale categories."""
    from datetime import datetime
    from io import BytesIO
    from pathlib import Path

    from PIL import Image, ImageDraw

    from tg_cleaner.core.hashing import compute_dhash, compute_text_hash

    db: DatabaseManager = request.app.state.db
    chat_id = 9999
    now = datetime.now(UTC)
    chat = ChatRecord(
        id=chat_id,
        title="Saved Messages (Interactive Demo)",
        chat_type="saved_messages",
        total_messages=7,
        last_scanned=now,
    )
    db.upsert_chat(chat)

    # Generate a demo thumbnail image
    thumbs_dir = Path("data") / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (320, 180), color=(14, 116, 144))
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 310, 170], outline=(56, 189, 248), width=3)
    img_bytes_io = BytesIO()
    img.save(img_bytes_io, format="JPEG")
    img_bytes = img_bytes_io.getvalue()
    demo_dhash = compute_dhash(img_bytes)

    with open(thumbs_dir / f"{chat_id}_3.jpg", "wb") as f:
        f.write(img_bytes)
    with open(thumbs_dir / f"{chat_id}_4.jpg", "wb") as f:
        f.write(img_bytes)

    messages = [
        MessageRecord(
            id=1,
            chat_id=chat_id,
            date=now.replace(hour=8, minute=0),
            text="Meeting notes: Architecture review on Telegram Archive Cleaner pipeline.",
            raw_text="Meeting notes: Architecture review on Telegram Archive Cleaner pipeline.",
            text_hash=compute_text_hash(
                "Meeting notes: Architecture review on Telegram Archive Cleaner pipeline."
            ),
        ),
        MessageRecord(
            id=2,
            chat_id=chat_id,
            date=now.replace(hour=8, minute=15),
            text="Meeting notes: Architecture review on Telegram Archive Cleaner pipeline.",
            raw_text="Meeting notes: Architecture review on Telegram Archive Cleaner pipeline.",
            text_hash=compute_text_hash(
                "Meeting notes: Architecture review on Telegram Archive Cleaner pipeline."
            ),
        ),
        MessageRecord(
            id=3,
            chat_id=chat_id,
            date=now.replace(hour=9, minute=0),
            text="Infographic: Distributed systems overview draft #notes",
            raw_text="Infographic: Distributed systems overview draft #notes",
            text_hash=compute_text_hash("Infographic: Distributed systems overview draft #notes"),
            media_type="photo",
            media_id="photo_demo_banner_99",
            dhash=demo_dhash,
            file_size=12040,
        ),
        MessageRecord(
            id=4,
            chat_id=chat_id,
            date=now.replace(hour=11, minute=30),
            text="Infographic: Distributed systems complete guide with full reference links & recommended reading list #notes #updated",
            raw_text="Infographic: Distributed systems complete guide with full reference links & recommended reading list #notes #updated",
            text_hash=compute_text_hash(
                "Infographic: Distributed systems complete guide with full reference links & recommended reading list #notes #updated"
            ),
            media_type="photo",
            media_id="photo_demo_banner_99",
            dhash=demo_dhash,
            file_size=12040,
        ),
        MessageRecord(
            id=5,
            chat_id=chat_id,
            date=now.replace(hour=12, minute=0),
            text="Old documentation link: https://httpstat.us/404",
            raw_text="Old documentation link: https://httpstat.us/404",
            has_links=True,
            extracted_urls=["https://httpstat.us/404"],
        ),
        MessageRecord(
            id=6,
            chat_id=chat_id,
            date=now.replace(hour=13, minute=0),
            text="Old study group link: https://t.me/+ExpiredDemoHash123",
            raw_text="Old study group link: https://t.me/+ExpiredDemoHash123",
            has_links=True,
            extracted_urls=["https://t.me/+ExpiredDemoHash123"],
        ),
        MessageRecord(
            id=7,
            chat_id=chat_id,
            date=now.replace(hour=14, minute=0),
            text="Media blocked by platform policy notice.",
            raw_text="Media blocked by platform policy notice.",
            restriction_reason="dmca:copyright_infringement_notice",
        ),
    ]
    db.upsert_messages(messages)

    dedupe_engine = DeduplicationEngine(db)
    dedupe_engine.detect_duplicates_in_chat(chat_id)

    policy_auditor = PolicyAuditor(db)
    policy_auditor.audit_policy_restrictions(chat_id)

    stats = db.get_scan_stats(chat_id)
    return {"chat_id": chat_id, "stats": stats.model_dump()}


@router.post("/chats/import-desktop")
async def import_desktop_export(
    request: Request,
    file: UploadFile | None = File(None),
) -> dict[str, Any]:
    """Import chat and messages from Telegram Desktop JSON export."""
    db: DatabaseManager = request.app.state.db

    if file:
        content = await file.read()
        try:
            export_dict = json.loads(content.decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON file: {e}") from e
    else:
        try:
            export_dict = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Missing JSON export payload") from None

    chat, messages = import_desktop_export_from_dict(export_dict, db)
    return {
        "chat_id": chat.id,
        "title": chat.title,
        "imported_count": len(messages),
    }


@router.get("/chats/{chat_id}/stats", response_model=ScanStats)
def get_chat_stats(chat_id: int, request: Request) -> ScanStats:
    """Retrieve aggregate scan statistics for a chat."""
    db: DatabaseManager = request.app.state.db
    return db.get_scan_stats(chat_id)


@router.get("/chats/{chat_id}/candidates", response_model=list[MessageRecord])
def get_deletion_candidates(chat_id: int, request: Request) -> list[MessageRecord]:
    """List all messages flagged as deletion candidates for a chat."""
    db: DatabaseManager = request.app.state.db
    return db.get_deletion_candidates(chat_id)


@router.get("/groups/{group_id}/diff")
def get_group_diff(group_id: str, request: Request) -> dict[str, Any]:
    """Retrieve side-by-side diff comparing messages in a duplicate group."""
    db: DatabaseManager = request.app.state.db
    group = db.get_duplicate_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Duplicate group not found")

    messages = db.get_messages_by_ids(group.chat_id, group.message_ids)
    flags = [f for f in db.get_flags_for_chat(group.chat_id) if f.group_id == group_id]

    return {
        "group_id": group.id,
        "chat_id": group.chat_id,
        "group_type": group.group_type.value,
        "suggested_keep_id": group.primary_message_id,
        "primary_message_id": group.primary_message_id,
        "recommended_preset": group.recommended_preset.value,
        "messages": [m.model_dump(mode="json") for m in messages],
        "flags": [f.model_dump(mode="json") for f in flags],
    }


@router.post("/groups/{group_id}/preset")
def update_group_preset(
    group_id: str, payload: PresetUpdateRequest, request: Request
) -> dict[str, Any]:
    """Apply a retention preset to a duplicate group and update candidate flags."""
    db: DatabaseManager = request.app.state.db
    group = db.get_duplicate_group(group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Duplicate group not found")

    engine = DeduplicationEngine(db)
    flags = engine.apply_retention_preset(group, payload.preset)
    return {
        "group_id": group.id,
        "preset": payload.preset.value,
        "updated_flags": len(flags),
    }


@router.post("/scan/{chat_id}", response_model=ScanResponse)
async def scan_chat(chat_id: int, request: Request) -> ScanResponse:
    """Run full audit pipeline (dedupe, links, policy, stale) on a chat."""
    db: DatabaseManager = request.app.state.db
    client = getattr(request.app.state, "client", None)

    db.clear_flags_for_chat(chat_id)

    # 1. Deduplication (Exact + Same Media Diff Caption)
    dedupe_engine = DeduplicationEngine(db)
    dedupe_flags = dedupe_engine.detect_duplicates_in_chat(chat_id)

    # 2. Policy auditor
    policy_auditor = PolicyAuditor(db)
    policy_flags = policy_auditor.audit_chat_policy(chat_id)

    # 3. Link health checker
    link_checker = LinkHealthChecker(db, client=client)
    link_flags = await link_checker.check_links_in_chat(chat_id)

    # 4. Stale analyzer
    stale_analyzer = StaleContentAnalyzer(db)
    stale_flags = stale_analyzer.audit_stale_content(chat_id)

    total_flags = len(dedupe_flags) + len(policy_flags) + len(link_flags) + len(stale_flags)
    stats = db.get_scan_stats(chat_id)

    return ScanResponse(chat_id=chat_id, flags_generated=total_flags, stats=stats)


@router.post("/delete/{chat_id}", response_model=DeletionResult)
async def delete_candidates(
    chat_id: int, payload: DeleteRequest, request: Request
) -> DeletionResult:
    """Execute pre-deletion backup and paced deletion of candidate messages."""
    db: DatabaseManager = request.app.state.db
    client = getattr(request.app.state, "client", None)
    backup_mgr: BackupManager = request.app.state.backup_manager

    executor = DeletionExecutor(
        db=db,
        client=client,
        backup_manager=backup_mgr,
        min_delay=0.1 if payload.dry_run else 1.2,
        max_delay=0.2 if payload.dry_run else 2.5,
    )

    try:
        return await executor.delete_candidates(
            chat_id=chat_id,
            message_ids=payload.message_ids,
            dry_run=payload.dry_run,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/backups")
def list_backups(request: Request) -> list[dict[str, Any]]:
    """List all created backups with SHA-256 metadata."""
    backup_mgr: BackupManager = request.app.state.backup_manager
    return backup_mgr.list_backups()


@router.get("/backups/{chat_id}")
def list_chat_backups(chat_id: int, request: Request) -> list[dict[str, Any]]:
    """List backups specifically for a given chat."""
    backup_mgr: BackupManager = request.app.state.backup_manager
    return backup_mgr.list_backups(chat_id=chat_id)


class AuthSendCodeRequest(BaseModel):
    """Payload to request Telegram login code."""

    phone: str


class AuthSignInRequest(BaseModel):
    """Payload to verify code and authenticate session."""

    phone: str
    code: str
    phone_code_hash: str
    password: str | None = None


@router.get("/auth/status")
async def get_auth_status(request: Request) -> dict[str, Any]:
    """Check Telegram client connection and authorization status."""
    try:
        from tg_cleaner.core.auth import TelegramAuthManager

        auth = TelegramAuthManager()
        is_auth = await auth.is_authorized()
        return {"authenticated": is_auth}
    except Exception as e:
        return {"authenticated": False, "error": str(e)}


@router.post("/auth/send-code")
async def auth_send_code(payload: AuthSendCodeRequest) -> dict[str, Any]:
    """Request a login verification code via Telegram."""
    try:
        from tg_cleaner.core.auth import TelegramAuthManager

        auth = TelegramAuthManager()
        phone_code_hash = await auth.send_login_code(payload.phone)
        return {"phone_code_hash": phone_code_hash}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/auth/sign-in")
async def auth_sign_in(payload: AuthSignInRequest) -> dict[str, Any]:
    """Complete Telegram authentication with code and optional 2FA password."""
    try:
        from tg_cleaner.core.auth import TelegramAuthManager

        auth = TelegramAuthManager()
        user = await auth.sign_in_with_code(
            phone=payload.phone,
            code=payload.code,
            phone_code_hash=payload.phone_code_hash,
            password=payload.password,
        )
        return {
            "success": True,
            "user_id": getattr(user, "id", None),
            "first_name": getattr(user, "first_name", "Telegram User"),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/media/{chat_id}/{message_id}")
def get_media_thumbnail(chat_id: int, message_id: int, request: Request) -> Any:
    """Serve cached image thumbnail or local media file if available."""
    from pathlib import Path

    from fastapi.responses import FileResponse

    db: DatabaseManager = request.app.state.db
    messages = db.get_messages_by_ids(chat_id, [message_id])
    if not messages:
        raise HTTPException(status_code=404, detail="Message not found")

    msg = messages[0]
    if msg.media_id:
        media_path = Path(msg.media_id)
        if media_path.is_file():
            return FileResponse(str(media_path))

    thumb_path = Path("data") / "thumbs" / f"{chat_id}_{message_id}.jpg"
    if thumb_path.is_file():
        return FileResponse(str(thumb_path))

    raise HTTPException(status_code=404, detail="No media or thumbnail available")


@router.get("/relay/status")
def get_relay_status() -> dict[str, Any]:
    """Return external edge relay configuration status."""
    from tg_cleaner.core.settings import settings

    configured = bool(settings.relay_url and settings.relay_shared_secret)
    provider_name = (
        "Cloudflare Worker"
        if configured and "workers.dev" in (settings.relay_url or "")
        else ("Custom Edge Relay" if configured else "Direct Local")
    )
    return {
        "configured": configured,
        "relay_url": settings.relay_url if configured else None,
        "provider": provider_name,
    }


@router.get("/backups/download/{filename}")
def download_backup_file(filename: str, request: Request) -> Any:
    """Download a local pre-deletion JSON backup archive."""
    safe_name = sanitize_filename(filename)
    backup_mgr = getattr(request.app.state, "backup_manager", None)
    backup_dir = Path(backup_mgr.backup_dir) if backup_mgr else Path("backups")
    file_path = backup_dir / safe_name
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found")
    return FileResponse(
        str(file_path),
        media_type="application/json",
        filename=safe_name,
    )


@router.post("/backups/{filename}/cloud-export")
async def export_backup_to_cloud(filename: str, payload: CloudExportRequest) -> dict[str, Any]:
    """Export a verified local backup archive to Google Drive or GitHub."""
    from tg_cleaner.cleaner.cloud_export import CloudExportManager
    from tg_cleaner.core.settings import settings

    manager = CloudExportManager(settings.backup_dir)
    if payload.provider == "github":
        if not payload.repo:
            raise HTTPException(
                status_code=400,
                detail="GitHub repository ('owner/repo') is required for export",
            )
        res = await manager.export_to_github(
            backup_filename=filename,
            token=payload.token,
            repo=payload.repo,
            branch=payload.branch,
        )
    elif payload.provider == "google_drive":
        res = await manager.export_to_google_drive(
            backup_filename=filename,
            access_token=payload.token,
            folder_id=payload.folder_id,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {payload.provider}")

    if not res.success:
        raise HTTPException(status_code=500, detail=res.error or "Export failed")

    return {
        "success": True,
        "provider": res.provider,
        "target_path": res.target_path,
        "web_link": res.web_link,
        "sha256": res.sha256,
        "bytes_uploaded": res.bytes_uploaded,
    }
