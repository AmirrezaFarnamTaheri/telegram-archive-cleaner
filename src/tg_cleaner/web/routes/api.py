"""REST API routes for Telegram Archive Cleaner dashboard."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tg_cleaner.analyzer.dedupe import DeduplicationEngine
from tg_cleaner.analyzer.links import LinkHealthChecker
from tg_cleaner.analyzer.llm import SemanticLLMAnalyzer
from tg_cleaner.analyzer.policy import PolicyAuditor
from tg_cleaner.analyzer.stale import StaleContentAnalyzer
from tg_cleaner.cleaner.backup import BackupManager
from tg_cleaner.cleaner.executor import DeletionExecutor, DeletionResult
from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import (
    ChatRecord,
    FlagType,
    MessageRecord,
    RetentionPreset,
    ScanStats,
)
from tg_cleaner.core.net_security import sanitize_filename
from tg_cleaner.core.settings import settings
from tg_cleaner.ingest.desktop_export import import_desktop_export_payload
from tg_cleaner.ingest.live import LiveIngestor

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


class CandidateResponse(MessageRecord):
    """Message plus the analysis details that caused it to be listed."""

    flag_type: FlagType
    recommended_for_deletion: bool = True
    flag_types: list[FlagType] = Field(default_factory=list)
    group_id: str | None = None
    confidence: float = 1.0
    reason: str = ""
    flag_details: list[dict[str, Any]] = Field(default_factory=list)


def _flag_reason(flag_type: FlagType, details: dict[str, Any]) -> str:
    """Turn flag details into a short reason for the UI."""
    explicit = details.get("reason")
    if explicit:
        return str(explicit)
    if details.get("preset"):
        preset = str(details["preset"]).replace("_", " ").title()
        return f"Retention choice: {preset}"
    if details.get("matched_by"):
        return f"Media matched by {details['matched_by']}"
    if details.get("restriction"):
        return f"Telegram restriction: {details['restriction']}"
    if details.get("media_type"):
        return f"Inaccessible {details['media_type']} media"
    if details.get("age_days") is not None:
        return f"Older than retention threshold: {details['age_days']} days"

    labels = {
        FlagType.DUPLICATE_EXACT_TEXT: "Exact duplicate text",
        FlagType.DUPLICATE_FUZZY_TEXT: "Near-duplicate text",
        FlagType.DUPLICATE_EXACT_MEDIA: "Exact duplicate media",
        FlagType.DUPLICATE_VISUAL_MEDIA: "Visually similar media (review required)",
        FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION: "Same media with a different caption",
        FlagType.DUPLICATE_FORWARD: "Duplicate forward chain",
        FlagType.STALE_DEAD_LINK: "Dead external link",
        FlagType.STALE_EXPIRED_INVITE: "Expired Telegram invite",
        FlagType.STALE_OUTDATED_TIME: "Stale content",
        FlagType.STALE_SUPERSEDED_LLM: "Superseded content",
        FlagType.POLICY_RESTRICTED: "Telegram policy restriction",
        FlagType.POLICY_EMPTY_MEDIA: "Empty or inaccessible media",
        FlagType.POLICY_DELETED_ACCOUNT: "Sender account no longer exists",
    }
    return labels.get(flag_type, flag_type.value.replace("_", " ").title())


@router.get("/health")
def get_health(request: Request) -> dict[str, Any]:
    """Health check endpoint checking database integrity."""
    db: DatabaseManager = request.app.state.db
    is_healthy = db.is_healthy()
    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "db_healthy": is_healthy,
        "api_auth_required": bool(settings.api_token),
    }


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

    if not settings.enable_demo_data:
        raise HTTPException(status_code=404, detail="Demo data generation is disabled")
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
    thumbs_dir = Path(request.app.state.thumb_dir)
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
            text="Meeting notes: Architecture review for Telegram Archive Cleaner.",
            raw_text="Meeting notes: Architecture review for Telegram Archive Cleaner.",
            text_hash=compute_text_hash(
                "Meeting notes: Architecture review for Telegram Archive Cleaner."
            ),
        ),
        MessageRecord(
            id=2,
            chat_id=chat_id,
            date=now.replace(hour=8, minute=15),
            text="Meeting notes: Architecture review for Telegram Archive Cleaner.",
            raw_text="Meeting notes: Architecture review for Telegram Archive Cleaner.",
            text_hash=compute_text_hash(
                "Meeting notes: Architecture review for Telegram Archive Cleaner."
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
    """Import a bounded single-chat or full Telegram Desktop JSON export."""
    db: DatabaseManager = request.app.state.db
    max_bytes = max(1024, settings.max_import_bytes)

    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > max_bytes + 2_000_000:
        raise HTTPException(status_code=413, detail="Import payload exceeds configured size limit")

    if file:
        content = bytearray()
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            content.extend(chunk)
            if len(content) > max_bytes:
                raise HTTPException(
                    status_code=413, detail="Import file exceeds configured size limit"
                )
        try:
            export_dict = json.loads(bytes(content).decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid UTF-8 JSON export") from exc
    else:
        body = await request.body()
        if len(body) > max_bytes:
            raise HTTPException(
                status_code=413, detail="Import payload exceeds configured size limit"
            )
        try:
            export_dict = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=400, detail="Invalid or missing JSON export payload"
            ) from exc

    try:
        imported = import_desktop_export_payload(export_dict, db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    messages_imported = sum(len(messages) for _, messages in imported)
    response: dict[str, Any] = {
        "chats_imported": len(imported),
        "messages_imported": messages_imported,
        "chat_ids": [chat.id for chat, _ in imported],
    }
    if len(imported) == 1:
        chat, messages = imported[0]
        response.update(
            {
                "chat_id": chat.id,
                "chat_title": chat.title,
                # Backward-compatible names for existing API consumers.
                "title": chat.title,
                "imported_count": len(messages),
            }
        )
    return response


@router.get("/chats/{chat_id}/stats", response_model=ScanStats)
def get_chat_stats(chat_id: int, request: Request) -> ScanStats:
    """Retrieve aggregate scan statistics for a chat."""
    db: DatabaseManager = request.app.state.db
    if not db.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return db.get_scan_stats(chat_id)


def _enriched_findings(
    db: DatabaseManager, chat_id: int, *, only_candidates: bool
) -> list[CandidateResponse]:
    flags = db.get_flags_for_chat(chat_id)
    if only_candidates:
        flags = [flag for flag in flags if flag.is_candidate_for_deletion]
    flags_by_message: dict[int, list[Any]] = {}
    for flag in flags:
        flags_by_message.setdefault(flag.message_id, []).append(flag)
    messages = db.get_messages_by_ids(chat_id, list(flags_by_message))
    messages = [message for message in messages if not message.is_deleted_locally]

    enriched: list[CandidateResponse] = []
    for message in sorted(messages, key=lambda item: item.date):
        message_flags = flags_by_message.get(message.id, [])
        if not message_flags:
            continue
        primary = message_flags[0]
        eligible = any(flag.is_candidate_for_deletion for flag in message_flags)
        enriched.append(
            CandidateResponse(
                **message.model_dump(),
                flag_type=primary.flag_type,
                recommended_for_deletion=eligible,
                flag_types=[flag.flag_type for flag in message_flags],
                group_id=primary.group_id,
                confidence=max(flag.confidence for flag in message_flags),
                reason=_flag_reason(primary.flag_type, primary.details),
                flag_details=[
                    {
                        "flag_type": flag.flag_type.value,
                        "group_id": flag.group_id,
                        "confidence": flag.confidence,
                        "recommended_for_deletion": flag.is_candidate_for_deletion,
                        "details": flag.details,
                    }
                    for flag in message_flags
                ],
            )
        )
    return enriched


@router.get("/chats/{chat_id}/findings", response_model=list[CandidateResponse])
def get_review_findings(chat_id: int, request: Request) -> list[CandidateResponse]:
    """Return all analysis results, including items that still need approval."""
    db: DatabaseManager = request.app.state.db
    if not db.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return _enriched_findings(db, chat_id, only_candidates=False)


@router.get("/chats/{chat_id}/candidates", response_model=list[CandidateResponse])
def get_deletion_candidates(chat_id: int, request: Request) -> list[CandidateResponse]:
    """Return only findings currently authorized by a deterministic rule or user review."""
    db: DatabaseManager = request.app.state.db
    if not db.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    return _enriched_findings(db, chat_id, only_candidates=True)


class FindingEligibilityRequest(BaseModel):
    """Explicit user approval/revocation for a review finding."""

    eligible: bool


@router.post("/chats/{chat_id}/findings/{message_id}/eligibility")
def set_finding_eligibility(
    chat_id: int, message_id: int, payload: FindingEligibilityRequest, request: Request
) -> dict[str, Any]:
    db: DatabaseManager = request.app.state.db
    if not db.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    updated = db.set_message_deletion_eligibility(chat_id, message_id, payload.eligible)
    if updated == 0:
        raise HTTPException(status_code=404, detail="No active finding exists for this message")
    return {"chat_id": chat_id, "message_id": message_id, "eligible": payload.eligible}


@router.get("/chats/{chat_id}/duplicate-groups")
def list_duplicate_groups(chat_id: int, request: Request) -> list[dict[str, Any]]:
    """Return complete duplicate groups, including keeper and candidate messages."""
    db: DatabaseManager = request.app.state.db
    all_flags = db.get_flags_for_chat(chat_id)
    result: list[dict[str, Any]] = []
    for group in db.get_duplicate_groups(chat_id):
        messages = db.get_messages_by_ids(chat_id, group.message_ids)
        flags = [flag for flag in all_flags if flag.group_id == group.id]
        result.append(
            {
                "group_id": group.id,
                "chat_id": group.chat_id,
                "group_type": group.group_type.value,
                "primary_message_id": group.primary_message_id,
                "suggested_keep_id": group.primary_message_id,
                "recommended_preset": group.recommended_preset.value,
                "diff_summary": group.diff_summary,
                "messages": [message.model_dump(mode="json") for message in messages],
                "flags": [flag.model_dump(mode="json") for flag in flags],
            }
        )
    return result


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
    """Run the configured analyzers and return the persisted result count."""
    db: DatabaseManager = request.app.state.db
    if not db.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    client = getattr(request.app.state, "client", None)

    DeduplicationEngine(db).detect_duplicates_in_chat(chat_id)
    PolicyAuditor(db).audit_chat_policy(chat_id)
    await LinkHealthChecker(db, client=client).check_links_in_chat(chat_id)
    StaleContentAnalyzer(db).audit_stale_content(chat_id, settings.stale_after_days)

    if settings.enable_llm_analysis:
        provider = settings.llm_provider.strip().lower()
        api_key = settings.openai_api_key if provider == "openai" else settings.gemini_api_key
        if api_key:
            await SemanticLLMAnalyzer(
                db, api_key=api_key, provider=provider, model=settings.llm_model
            ).analyze_superseded_messages(chat_id)

    flags_generated = len(db.get_flags_for_chat(chat_id))
    return ScanResponse(
        chat_id=chat_id, flags_generated=flags_generated, stats=db.get_scan_stats(chat_id)
    )


@router.post("/delete/{chat_id}", response_model=DeletionResult)
async def delete_candidates(
    chat_id: int, payload: DeleteRequest, request: Request
) -> DeletionResult:
    """Back up and process only messages that are still current deletion candidates."""
    db: DatabaseManager = request.app.state.db
    backup_mgr: BackupManager = request.app.state.backup_manager

    if not payload.message_ids:
        raise HTTPException(status_code=400, detail="No messages selected")
    if len(payload.message_ids) != len(set(payload.message_ids)):
        raise HTTPException(status_code=400, detail="Duplicate message IDs are not allowed")

    allowed_ids = {message.id for message in db.get_deletion_candidates(chat_id)}
    requested_ids = set(payload.message_ids)
    rejected = sorted(requested_ids - allowed_ids)
    if rejected:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Selection is stale or includes messages that are no longer deletion candidates",
                "rejected_message_ids": rejected,
            },
        )

    client = getattr(request.app.state, "client", None)
    if not payload.dry_run and client is None:
        from tg_cleaner.core.auth import TelegramAuthManager

        auth = TelegramAuthManager()
        if not await auth.is_authorized():
            raise HTTPException(
                status_code=401,
                detail="Live deletion requires an authorized Telegram session",
            )
        client = auth.get_client()
        request.app.state.client = client

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
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/backups")
def list_backups(request: Request) -> list[dict[str, Any]]:
    """List all created backups with SHA-256 metadata."""
    backup_mgr: BackupManager = request.app.state.backup_manager
    return backup_mgr.list_backups()


@router.get("/backups/{filename}/verify")
def verify_backup_file(filename: str, request: Request) -> dict[str, Any]:
    """Recompute a backup checksum and report whether the snapshot is valid."""
    backup_mgr: BackupManager = request.app.state.backup_manager
    safe_name = sanitize_filename(filename)
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    path = Path(backup_mgr.backup_dir) / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Backup file not found")

    valid = backup_mgr.verify_backup(path)
    sha256: str | None = None
    try:
        with open(path, encoding="utf-8") as file_handle:
            sha256 = json.load(file_handle).get("sha256")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        valid = False

    return {"valid": valid, "sha256": sha256, "filename": safe_name}


@router.get("/backups/{chat_id}")
def list_chat_backups(chat_id: int, request: Request) -> list[dict[str, Any]]:
    """List backups specifically for a given chat."""
    backup_mgr: BackupManager = request.app.state.backup_manager
    return backup_mgr.list_backups(chat_id=chat_id)


class AuthSendCodeRequest(BaseModel):
    """Payload to request Telegram login code."""

    phone: str = Field(min_length=5, max_length=32)
    api_id: int | None = Field(default=None, gt=0)
    api_hash: str | None = Field(default=None, min_length=16, max_length=128)
    proxy_type: str | None = None
    proxy_host: str | None = None
    proxy_port: int | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    proxy_secret: str | None = None


class AuthSignInRequest(BaseModel):
    """Payload to verify code and authenticate session."""

    phone: str = Field(min_length=5, max_length=32)
    code: str = Field(min_length=1, max_length=16)
    phone_code_hash: str = Field(min_length=8, max_length=256)
    password: str | None = Field(default=None, max_length=512)


class AuthCredentialsRequest(BaseModel):
    """Payload to configure and persist Telegram API credentials and proxy settings."""

    api_id: int | None = Field(default=None, gt=0)
    api_hash: str | None = Field(default=None, min_length=16, max_length=128)
    phone: str | None = Field(default=None, min_length=5, max_length=32)
    proxy_type: str | None = None
    proxy_host: str | None = None
    proxy_port: int | None = None
    proxy_username: str | None = None
    proxy_password: str | None = None
    proxy_secret: str | None = None


@router.get("/auth/status")
async def get_auth_status(request: Request) -> dict[str, Any]:
    """Check Telegram client connection, credentials and authorization status."""
    from tg_cleaner.core.settings import settings

    has_creds = bool(settings.telegram_api_id and settings.telegram_api_hash)
    proxy_configured = bool(settings.telegram_proxy_type and settings.telegram_proxy_host)
    try:
        from tg_cleaner.core.auth import TelegramAuthManager

        auth = TelegramAuthManager()
        is_auth = await auth.is_authorized() if has_creds else False
        return {
            "authenticated": is_auth,
            "has_credentials": has_creds,
            "api_id": settings.telegram_api_id,
            "phone": settings.telegram_phone,
            "proxy_configured": proxy_configured,
            "proxy_type": settings.telegram_proxy_type,
            "proxy_host": settings.telegram_proxy_host,
            "proxy_port": settings.telegram_proxy_port,
        }
    except Exception as e:
        return {
            "authenticated": False,
            "has_credentials": has_creds,
            "proxy_configured": proxy_configured,
            "error": str(e),
        }


async def _discard_app_client(request: Request) -> None:
    """Safely disconnect and discard any active TelegramClient on app state."""
    active = getattr(request.app.state, "client", None)
    if active is not None:
        disconnect = getattr(active, "disconnect", None)
        if callable(disconnect):
            try:
                result = disconnect()
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                pass
        request.app.state.client = None


@router.post("/auth/credentials")
async def save_auth_credentials(
    payload: AuthCredentialsRequest, request: Request
) -> dict[str, Any]:
    """Persist Telegram API/proxy configuration and invalidate the active client."""
    from tg_cleaner.core.settings import update_credentials_and_save

    await _discard_app_client(request)

    update_credentials_and_save(
        api_id=payload.api_id,
        api_hash=payload.api_hash,
        phone=payload.phone,
        proxy_type=payload.proxy_type,
        proxy_host=payload.proxy_host,
        proxy_port=payload.proxy_port,
        proxy_username=payload.proxy_username,
        proxy_password=payload.proxy_password,
        proxy_secret=payload.proxy_secret,
    )
    return {"status": "ok"}


@router.post("/auth/send-code")
async def auth_send_code(payload: AuthSendCodeRequest, request: Request) -> dict[str, Any]:
    """Request a login verification code via Telegram."""
    from tg_cleaner.core.auth import TelegramAuthManager
    from tg_cleaner.core.settings import settings, update_credentials_and_save

    await _discard_app_client(request)

    update_credentials_and_save(
        api_id=payload.api_id,
        api_hash=payload.api_hash,
        phone=payload.phone,
        proxy_type=payload.proxy_type,
        proxy_host=payload.proxy_host,
        proxy_port=payload.proxy_port,
        proxy_username=payload.proxy_username,
        proxy_password=payload.proxy_password,
        proxy_secret=payload.proxy_secret,
    )

    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise HTTPException(
            status_code=400,
            detail="Telegram API credentials missing. Please provide your API ID and API Hash from https://my.telegram.org.",
        )

    try:
        auth = TelegramAuthManager()
        auth.reset_client()
        phone_code_hash = await auth.send_login_code(payload.phone)
        return {"phone_code_hash": phone_code_hash}
    except Exception as e:
        msg = str(e)
        if any(
            term in msg.lower()
            for term in ["timeout", "timed out", "connection", "connect", "refused"]
        ):
            msg += ". If direct access to Telegram MTProto is blocked by your network provider, please configure a SOCKS5 or HTTP proxy in the proxy settings."
        raise HTTPException(status_code=400, detail=msg) from e


@router.post("/auth/sign-in")
async def auth_sign_in(payload: AuthSignInRequest, request: Request) -> dict[str, Any]:
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
        request.app.state.client = auth.get_client()
        return {
            "success": True,
            "status": "ok",
            "user_id": getattr(user, "id", None),
            "first_name": getattr(user, "first_name", "Telegram User"),
        }
    except ValueError as exc:
        if "2fa password required" in str(exc).lower():
            return {"success": False, "status": "2fa_required"}
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/auth/logout")
async def auth_logout(request: Request) -> dict[str, Any]:
    """Log out the current Telegram session and discard the in-process client."""
    from tg_cleaner.core.auth import TelegramAuthManager

    active = getattr(request.app.state, "client", None)
    try:
        if active is not None and callable(getattr(active, "log_out", None)):
            await active.log_out()
        else:
            auth = TelegramAuthManager()
            if await auth.is_authorized():
                await auth.logout()
    finally:
        await _discard_app_client(request)
    return {"status": "ok"}


class LivePullRequest(BaseModel):
    """Request to pull a live Telegram chat into the local staging database."""

    chat: str = Field(min_length=1, max_length=256)
    limit: int | None = Field(default=1000, ge=1, le=100000)


async def _authorized_client(request: Request) -> Any:
    client = getattr(request.app.state, "client", None)
    if client is not None:
        try:
            if not client.is_connected():
                await client.connect()
            if await client.is_user_authorized():
                return client
        except Exception:
            request.app.state.client = None

    from tg_cleaner.core.auth import TelegramAuthManager

    auth = TelegramAuthManager()
    if not await auth.is_authorized():
        raise HTTPException(status_code=401, detail="Telegram authorization required")
    client = auth.get_client()
    request.app.state.client = client
    return client


@router.get("/telegram/dialogs", response_model=list[ChatRecord])
async def list_telegram_dialogs(request: Request, limit: int = 100) -> list[ChatRecord]:
    """Fetch Telegram dialogs and refresh their local chat metadata."""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 1000")
    client = await _authorized_client(request)
    db: DatabaseManager = request.app.state.db
    dialogs = await LiveIngestor(client, db, data_saver_mode=settings.data_saver_mode).list_dialogs(
        limit
    )
    for chat in dialogs:
        db.upsert_chat(chat)
    return dialogs


@router.post("/telegram/pull")
async def pull_live_chat(payload: LivePullRequest, request: Request) -> dict[str, Any]:
    """Resolve a Telegram peer and ingest its latest/full history into the staging DB."""
    client = await _authorized_client(request)
    try:
        entity = await client.get_entity(payload.chat)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Telegram chat could not be resolved") from exc
    db: DatabaseManager = request.app.state.db
    ingestor = LiveIngestor(client, db, data_saver_mode=settings.data_saver_mode)
    count = await ingestor.ingest_chat(entity, limit=payload.limit)
    chat_id = None
    try:
        from telethon import utils

        chat_id = int(utils.get_peer_id(entity))
    except Exception:
        chat_id = getattr(entity, "id", None)
    return {"chat_id": chat_id, "messages_imported": count}


@router.get("/media/{chat_id}/{message_id}")
def get_media_thumbnail(chat_id: int, message_id: int, request: Request) -> Any:
    """Serve only application-managed thumbnails for a known message.

    Desktop export ``file`` fields are untrusted input. Treating ``media_id`` as
    an arbitrary filesystem path would turn the dashboard into a local-file read
    primitive, so previews are restricted to the managed thumbnail cache.
    """
    db: DatabaseManager = request.app.state.db
    messages = db.get_messages_by_ids(chat_id, [message_id])
    if not messages:
        raise HTTPException(status_code=404, detail="Message not found")

    thumb_root = Path(request.app.state.thumb_dir).resolve()
    thumb_path = (thumb_root / f"{chat_id}_{message_id}.jpg").resolve()
    try:
        thumb_path.relative_to(thumb_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid media reference") from exc
    if thumb_path.is_file():
        return FileResponse(str(thumb_path))

    raise HTTPException(status_code=404, detail="No managed thumbnail available")


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
        "provider": provider_name,
    }


@router.get("/backups/download/{filename}")
def download_backup_file(filename: str, request: Request) -> Any:
    """Download a local pre-deletion JSON backup archive."""
    safe_name = sanitize_filename(filename)
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
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
async def export_backup_to_cloud(
    filename: str, payload: CloudExportRequest, request: Request
) -> dict[str, Any]:
    """Export a verified local backup archive to Google Drive or GitHub."""
    from tg_cleaner.cleaner.cloud_export import CloudExportManager

    manager = CloudExportManager(request.app.state.backup_manager.backup_dir)
    safe_name = sanitize_filename(filename)
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid backup filename")
    if payload.provider == "github":
        if not payload.repo:
            raise HTTPException(
                status_code=400,
                detail="GitHub repository ('owner/repo') is required for export",
            )
        res = await manager.export_to_github(
            backup_filename=safe_name,
            token=payload.token,
            repo=payload.repo,
            branch=payload.branch,
        )
    elif payload.provider == "google_drive":
        res = await manager.export_to_google_drive(
            backup_filename=safe_name,
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
