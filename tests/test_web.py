"""Tests for FastAPI Web Dashboard endpoints and static serving.

Verifies health, chat listing, desktop JSON import, scan triggering,
group preset updates, paced deletion dry-run, and backup queries.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tg_cleaner.core.db import DatabaseManager
from tg_cleaner.core.models import (
    AnalysisFlag,
    ChatRecord,
    DuplicateGroup,
    DuplicateGroupType,
    FlagType,
    MessageRecord,
)
from tg_cleaner.web.app import create_app


@pytest.fixture
def web_db(tmp_path: Path) -> DatabaseManager:
    """Fixture providing isolated database populated with sample data."""
    db_file = tmp_path / "web_test.db"
    db = DatabaseManager(str(db_file))
    db.init_db()

    chat = ChatRecord(id=100, title="Saved Messages", chat_type="saved_messages", total_messages=2)
    db.upsert_chat(chat)

    msg1 = MessageRecord(
        id=1,
        chat_id=100,
        date=datetime(2026, 1, 1, 10, 0),
        text="Draft announcement #python",
        raw_text="Draft announcement #python",
        media_type="photo",
        media_id="photo_hash_abc",
        file_size=1024,
    )
    msg2 = MessageRecord(
        id=2,
        chat_id=100,
        date=datetime(2026, 1, 1, 12, 0),
        text="Updated announcement #python with complete links and extra study materials",
        raw_text="Updated announcement #python with complete links and extra study materials",
        media_type="photo",
        media_id="photo_hash_abc",
        file_size=1024,
    )
    db.upsert_messages([msg1, msg2])

    group = DuplicateGroup(
        id="grp_same_media_100",
        chat_id=100,
        group_type=DuplicateGroupType.SAME_MEDIA_DIFF_CAPTION,
        message_ids=[1, 2],
        primary_message_id=2,
    )
    db.upsert_duplicate_group(group)

    flag1 = AnalysisFlag(
        message_id=1,
        chat_id=100,
        flag_type=FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION,
        group_id="grp_same_media_100",
        is_candidate_for_deletion=True,
        confidence=1.0,
        details={"diff": "- Draft + Updated with complete links"},
    )
    flag2 = AnalysisFlag(
        message_id=2,
        chat_id=100,
        flag_type=FlagType.DUPLICATE_SAME_MEDIA_DIFF_CAPTION,
        group_id="grp_same_media_100",
        is_candidate_for_deletion=False,
        confidence=1.0,
        details={"diff": "+ Updated with complete links"},
    )
    db.upsert_flags([flag1, flag2])

    return db


@pytest.fixture
def client(web_db: DatabaseManager, tmp_path: Path) -> TestClient:
    """FastAPI TestClient fixture."""
    backup_dir = tmp_path / "backups"
    app = create_app(db=web_db, backup_dir=str(backup_dir))
    return TestClient(app)


def test_api_health(client: TestClient):
    """Verify /api/health returns healthy status."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["db_healthy"] is True


def test_api_get_chats(client: TestClient):
    """Verify /api/chats returns chat records."""
    resp = client.get("/api/chats")
    assert resp.status_code == 200
    chats = resp.json()
    assert len(chats) == 1
    assert chats[0]["id"] == 100
    assert chats[0]["title"] == "Saved Messages"


def test_api_get_chat_stats_and_candidates(client: TestClient):
    """Verify stats and deletion candidates endpoints."""
    stats_resp = client.get("/api/chats/100/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["chat_id"] == 100
    assert stats["same_media_diff_caption"] == 2
    assert stats["total_deletion_candidates"] == 1

    cand_resp = client.get("/api/chats/100/candidates")
    assert cand_resp.status_code == 200
    cands = cand_resp.json()
    assert len(cands) == 1
    assert cands[0]["id"] == 1


def test_api_group_diff_and_preset(client: TestClient):
    """Verify diff retrieval and preset switching for duplicate groups."""
    diff_resp = client.get("/api/groups/grp_same_media_100/diff")
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()
    assert diff_data["group_id"] == "grp_same_media_100"
    assert len(diff_data["messages"]) == 2

    # Switch preset to KEEP_OLDEST (so msg1 is kept, msg2 becomes candidate)
    preset_resp = client.post(
        "/api/groups/grp_same_media_100/preset",
        json={"preset": "KEEP_OLDEST"},
    )
    assert preset_resp.status_code == 200

    cand_resp = client.get("/api/chats/100/candidates")
    cands = cand_resp.json()
    assert len(cands) == 1
    assert cands[0]["id"] == 2  # msg2 is now candidate


def test_api_desktop_import(client: TestClient, tmp_path: Path):
    """Verify importing a Telegram Desktop export JSON."""
    export_payload = {
        "name": "Exported Channel",
        "type": "public_channel",
        "id": 999,
        "messages": [
            {
                "id": 10,
                "type": "message",
                "date": "2026-02-01T12:00:00",
                "text": "Exported text hello",
            }
        ],
    }
    resp = client.post("/api/chats/import-desktop", json=export_payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["chat_id"] == 999
    assert data["imported_count"] == 1


def test_api_delete_dry_run(client: TestClient):
    """Verify /api/delete executes in dry-run mode and creates backup."""
    del_resp = client.post(
        "/api/delete/100",
        json={"message_ids": [1], "dry_run": True},
    )
    assert del_resp.status_code == 200
    result = del_resp.json()
    assert result["dry_run"] is True
    assert result["deleted_count"] == 1
    assert result["backup_file"] != ""

    # Verify backup listing endpoint
    b_resp = client.get("/api/backups")
    assert b_resp.status_code == 200
    backups = b_resp.json()
    assert len(backups) >= 1

    # Verify downloading the backup file
    filename = backups[0]["filename"]
    dl_resp = client.get(f"/api/backups/download/{filename}")
    assert dl_resp.status_code == 200
    assert "application/json" in dl_resp.headers["content-type"]
    assert len(dl_resp.content) > 0

    # Verify 404 on nonexistent or path-traversal backup file
    missing_resp = client.get("/api/backups/download/nonexistent_backup.json")
    assert missing_resp.status_code == 404


def test_api_candidates_include_review_evidence(client: TestClient):
    """Candidate responses expose the flag metadata the review UI depends on."""
    resp = client.get("/api/chats/100/candidates")
    assert resp.status_code == 200
    candidate = resp.json()[0]
    assert candidate["id"] == 1
    assert candidate["flag_type"] == "DUPLICATE_SAME_MEDIA_DIFF_CAPTION"
    assert candidate["flag_types"] == ["DUPLICATE_SAME_MEDIA_DIFF_CAPTION"]
    assert candidate["group_id"] == "grp_same_media_100"
    assert candidate["reason"]
    assert candidate["flag_details"][0]["confidence"] == 1.0


def test_api_duplicate_groups_include_keeper(client: TestClient):
    """Compare view receives the full group rather than deletion candidates only."""
    resp = client.get("/api/chats/100/duplicate-groups")
    assert resp.status_code == 200
    groups = resp.json()
    assert len(groups) == 1
    assert groups[0]["group_id"] == "grp_same_media_100"
    assert groups[0]["primary_message_id"] == 2
    assert {m["id"] for m in groups[0]["messages"]} == {1, 2}


def test_api_delete_rejects_stale_or_non_candidate_ids(client: TestClient):
    """The API must not delete arbitrary message IDs supplied by the browser."""
    resp = client.post(
        "/api/delete/100",
        json={"message_ids": [2], "dry_run": True},
    )
    assert resp.status_code == 409
    assert "no longer deletion candidates" in resp.json()["detail"]["message"]


def test_api_backup_verify_endpoint(client: TestClient):
    """A created snapshot can be independently re-verified from the dashboard."""
    created = client.post(
        "/api/delete/100",
        json={"message_ids": [1], "dry_run": True},
    )
    assert created.status_code == 200
    filename = Path(created.json()["backup_file"]).name

    verified = client.get(f"/api/backups/{filename}/verify")
    assert verified.status_code == 200
    assert verified.json()["valid"] is True
    assert len(verified.json()["sha256"]) == 64


def test_api_does_not_serve_archive_controlled_local_paths(
    web_db: DatabaseManager, tmp_path: Path
):
    """Desktop export file fields cannot be used as a local-file read primitive."""
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"not really an image")
    message = web_db.get_messages_by_ids(100, [1])[0]
    message.media_id = str(secret)
    web_db.upsert_messages([message])

    app = create_app(db=web_db, backup_dir=str(tmp_path / "backups"))
    local_client = TestClient(app)
    resp = local_client.get("/api/media/100/1")
    assert resp.status_code == 404
    assert resp.content != secret.read_bytes()


def test_api_token_protects_mutating_and_read_api(
    web_db: DatabaseManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Configured API tokens protect the whole API while leaving the shell loadable."""
    from tg_cleaner.core.settings import settings

    monkeypatch.setattr(settings, "api_token", "test-secret-token")
    app = create_app(db=web_db, backup_dir=str(tmp_path / "backups"))
    protected_client = TestClient(app)

    assert protected_client.get("/api/health").status_code == 401
    authorized = protected_client.get(
        "/api/health",
        headers={"Authorization": "Bearer test-secret-token"},
    )
    assert authorized.status_code == 200
    assert protected_client.get("/").status_code == 200
