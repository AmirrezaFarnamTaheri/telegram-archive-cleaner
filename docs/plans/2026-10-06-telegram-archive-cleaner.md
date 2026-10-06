# Telegram Archive Cleaner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the repository into a production-grade Telegram Archive Cleaner capable of auditing any chat (Saved Messages, channels, groups, or desktop JSON exports), detecting duplicates (including same media with different captions), finding broken/stale content and policy deletions, creating mandatory pre-deletion backups, and executing paced deletions via a responsive FastAPI web dashboard or CLI.

**Architecture:** Decoupled SQLite staging cache stores message metadata offline. Multi-engine analyzers process messages offline for exact/fuzzy duplicates, same-media/different-caption diffs, dead HTTP links, expired Telegram invites, temporal deadlines, and policy restrictions. A paced deletion executor enforces pre-deletion JSON backups and respects Telegram's 100-message batch limits and FloodWait delays. A FastAPI backend serves an embedded SPA with visual diff cards and preset selectors.

**Tech Stack:** Python 3.11+, Telethon 1.43+, SQLite (WAL mode), FastAPI 0.124+, Uvicorn 0.53+, Pillow 12.3+ (perceptual dHash), HTTPX 0.27+, Pydantic 2.13+, Typer 0.12+, Tailwind CSS + Alpine.js.

## Global Constraints
- Python 3.11+ compatibility.
- Zero data loss: Deletions require a verified local JSON snapshot in `backups/`.
- Zero multi-gigabyte media downloads: Deduplication uses Telegram metadata and micro-thumbnails (`thumb=0`) only.
- Strict rate pacing: Max 100 messages per RPC deletion call, 1.2s - 2.5s jittered delays, automatic sleep on `FloodWaitError`.
- No Node.js build requirement: Web UI is an embedded SPA using Tailwind CSS CDN and Alpine.js served directly by FastAPI.
- Pure Python fallback for fuzzy string matching and perceptual hashing to avoid native binary compilation issues.

---

### Task 1: Core Configuration and Database Staging Layer

**Files:**
- Create: `src/tg_cleaner/__init__.py`
- Create: `src/tg_cleaner/core/__init__.py`
- Create: `src/tg_cleaner/core/settings.py`
- Create: `src/tg_cleaner/core/models.py`
- Create: `src/tg_cleaner/core/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: Standard library `sqlite3`, `pydantic`, `pydantic-settings`.
- Produces:
  - `Settings`: Pydantic settings loading `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_NAME`, `DB_PATH`, `BACKUP_DIR`, `GEMINI_API_KEY`.
  - `MessageRecord`: Data model for staged Telegram messages with media metadata, text hashes, entities, and flags.
  - `AnalysisFlag`: Flag model (`flag_type`, `severity`, `confidence`, `details`, `group_id`).
  - `DuplicateGroup`: Model representing clustered duplicate messages with diff metrics.
  - `DatabaseManager`: Class managing SQLite connection in WAL mode, schema initialization, message upserting, flag persistence, and batch querying.

- [ ] **Step 1: Write the failing database tests**
Create `tests/test_db.py` testing database initialization, inserting `MessageRecord` objects, retrieving by chat ID, inserting and querying analysis flags, and updating deletion statuses.

- [ ] **Step 2: Run test to verify failure**
Run `pytest tests/test_db.py` and confirm `ModuleNotFoundError: No module named 'tg_cleaner'`.

- [ ] **Step 3: Implement Settings and Models**
Implement `src/tg_cleaner/core/settings.py` and `src/tg_cleaner/core/models.py` with complete Pydantic models for messages, flags, groups, presets, and deletion batches.

- [ ] **Step 4: Implement DatabaseManager**
Implement `src/tg_cleaner/core/db.py` with SQLite schema (`chats`, `messages`, `analysis_flags`, `duplicate_groups`, `backups`, `deletion_logs`), WAL mode, indexes on `(chat_id, message_id)`, `text_hash`, `media_id`, and transaction helpers.

- [ ] **Step 5: Run tests and verify pass**
Run `pytest tests/test_db.py` and verify all tests pass.

---

### Task 2: Perceptual Hashing & Text Normalization Utilities

**Files:**
- Create: `src/tg_cleaner/core/hashing.py`
- Test: `tests/test_hashing.py`

**Interfaces:**
- Consumes: `Pillow` (PIL.Image), `hashlib`, `unicodedata`.
- Produces:
  - `normalize_text(text: str) -> str`: NFKC normalization, strip zero-width characters and emojis, lowercase, whitespace collapse.
  - `compute_text_hash(text: str) -> str`: SHA-256 hex digest of normalized text.
  - `compute_dhash(image_bytes: bytes, hash_size: int = 8) -> str`: 64-bit difference hash computed from image thumbnail.
  - `hamming_distance(hash1: str, hash2: str) -> int`: Number of differing bits between two 16-character hex dHash strings.
  - `token_sort_ratio(s1: str, s2: str) -> float`: Normalized string similarity in [0, 100] using rapidfuzz or pure-Python Levenshtein fallback.

- [ ] **Step 1: Write the failing hashing & text tests**
Create `tests/test_hashing.py` testing text normalization edge cases, SHA-256 consistency, dHash calculation on synthetic PIL images, Hamming distance calculation, and token sort ratio.

- [ ] **Step 2: Run test to verify failure**
Run `pytest tests/test_hashing.py` to confirm failure.

- [ ] **Step 3: Implement hashing and normalization**
Implement `src/tg_cleaner/core/hashing.py` with difference hashing (dHash) without deprecation warnings, Hamming distance bit-operations, Unicode normalization, and Levenshtein token sorting.

- [ ] **Step 4: Run tests and verify pass**
Run `pytest tests/test_hashing.py` and verify 100% pass.

---

### Task 3: Ingestion Subsystem (Telegram Live MTProto & Desktop Export)

**Files:**
- Create: `src/tg_cleaner/ingest/__init__.py`
- Create: `src/tg_cleaner/ingest/live.py`
- Create: `src/tg_cleaner/ingest/desktop_export.py`
- Test: `tests/test_ingest.py`

**Interfaces:**
- Consumes: `telethon.TelegramClient`, `src/tg_cleaner/core/models.py`, `src/tg_cleaner/core/db.py`, `src/tg_cleaner/core/hashing.py`.
- Produces:
  - `LiveIngestor`: Async service fetching messages via `client.iter_messages`, extracting photo/document IDs, file size, mime, duration, dimensions, restriction reasons, downloading `thumb=0` for dHash computation, and saving to SQLite.
  - `DesktopExportParser`: Parses Telegram Desktop `result.json` export files, resolves mixed text entity arrays, extracts media references, computes text hashes, and populates SQLite.

- [ ] **Step 1: Write the failing ingestion tests**
Create `tests/test_ingest.py` with mock Telegram Desktop `result.json` test fixtures (plain text, media with caption, media without caption, service messages) and mock Telethon message objects.

- [ ] **Step 2: Run test to verify failure**
Run `pytest tests/test_ingest.py` to confirm failure.

- [ ] **Step 3: Implement DesktopExportParser**
Implement `src/tg_cleaner/ingest/desktop_export.py` parsing `result.json` structures safely, converting ISO timestamps, handling entity objects, and saving `MessageRecord` rows into the staging DB.

- [ ] **Step 4: Implement LiveIngestor**
Implement `src/tg_cleaner/ingest/live.py` with pagination cursor checkpointing, cancellation support, progress emission callbacks, and defensive attribute extraction from MTProto types.

- [ ] **Step 5: Run tests and verify pass**
Run `pytest tests/test_ingest.py` and verify all tests pass.

---

### Task 4: Deduplication Engine (Exact, Fuzzy & Same Media / Different Captions)

**Files:**
- Create: `src/tg_cleaner/analyzer/__init__.py`
- Create: `src/tg_cleaner/analyzer/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Consumes: `src/tg_cleaner/core/db.py`, `src/tg_cleaner/core/models.py`, `src/tg_cleaner/core/hashing.py`.
- Produces:
  - `DeduplicationEngine`: Scans staged messages in a chat and classifies:
    - `EXACT_TEXT`: Identical `text_hash` and non-empty text.
    - `FUZZY_TEXT`: Token sort ratio $\ge 90$ with character count $\ge 30$.
    - `EXACT_MEDIA`: Identical `media_id` (or identical `size + mime + duration`) with identical caption.
    - `SAME_MEDIA_DIFF_CAPTION`: Identical media asset or perceptual dHash distance $\le 3$, but divergent caption text.
    - `FORWARD_DUPLICATE`: Identical `fwd_from_id` and `fwd_channel_post`.
  - Diff Computation:
    - Generates inline character/word diff representation between captions.
    - Computes length delta ($\Delta \text{chars}$), link changes, and update markers.
  - Smart Retention Resolver:
    - Applies presets (`KEEP_NEWEST`, `KEEP_LONGEST`, `KEEP_OLDEST`, `WHITELIST_ALL`) to select the default keeper and mark redundant messages for deletion.

- [ ] **Step 1: Write the failing deduplication tests**
Create `tests/test_dedupe.py` with test scenarios:
  1. Exact text duplicate messages.
  2. Same media (same photo ID) with identical captions.
  3. Same media with updated/rescheduled announcement caption (`SAME_MEDIA_DIFF_CAPTION`).
  4. Same media with bare vs detailed note caption.
  5. Applying retention presets (`KEEP_NEWEST`, `KEEP_LONGEST`, `KEEP_OLDEST`).
  6. Diff generator output validation.

- [ ] **Step 2: Run test to verify failure**
Run `pytest tests/test_dedupe.py` to confirm failure.

- [ ] **Step 3: Implement DeduplicationEngine**
Implement `src/tg_cleaner/analyzer/dedupe.py` with SQL grouping, multi-tier media fingerprinting, dHash clustering, diff generation, and preset recommendation logic.

- [ ] **Step 4: Run tests and verify pass**
Run `pytest tests/test_dedupe.py` and verify all tests pass.

---

### Task 5: Link Checker, Policy Auditor & Stale Content Analyzers

**Files:**
- Create: `src/tg_cleaner/analyzer/links.py`
- Create: `src/tg_cleaner/analyzer/stale.py`
- Create: `src/tg_cleaner/analyzer/policy.py`
- Create: `src/tg_cleaner/analyzer/llm.py`
- Test: `tests/test_analyzers.py`

**Interfaces:**
- Consumes: `httpx.AsyncClient`, `telethon.functions.messages.CheckChatInviteRequest`, `src/tg_cleaner/core/db.py`.
- Produces:
  - `LinkHealthChecker`: Asynchronously tests extracted HTTP links for 404/410/DNS errors; tests `t.me/+...` invite links via Telethon catching `InviteHashExpiredError`.
  - `StaleContentAnalyzer`: Flags messages older than user cutoff (e.g. 90/180/365 days) and parses expired date/deadline strings.
  - `PolicyAuditor`: Flags messages with non-empty `restriction_reason`, `MessageMediaEmpty`, or `is_deleted_sender == True`.
  - `SemanticLLMAnalyzer`: Optional LLM evaluator (Gemini / OpenAI) detecting superseded messages in thread context when API key is provided.

- [ ] **Step 1: Write the failing analyzer tests**
Create `tests/test_analyzers.py` testing dead link detection with respx/mock responses, invite hash parsing, cutoff date filtering, restriction reason evaluation, and deleted account identification.

- [ ] **Step 2: Run test to verify failure**
Run `pytest tests/test_analyzers.py` to confirm failure.

- [ ] **Step 3: Implement LinkHealthChecker, StaleContentAnalyzer, PolicyAuditor & SemanticLLMAnalyzer**
Implement each module in `src/tg_cleaner/analyzer/` with robust error handling and database flag persistence.

- [ ] **Step 4: Run tests and verify pass**
Run `pytest tests/test_analyzers.py` and verify all tests pass.

---

### Task 6: Pre-Deletion Backup & Paced Deletion Execution

**Files:**
- Create: `src/tg_cleaner/cleaner/__init__.py`
- Create: `src/tg_cleaner/cleaner/backup.py`
- Create: `src/tg_cleaner/cleaner/executor.py`
- Test: `tests/test_cleaner.py`

**Interfaces:**
- Consumes: `src/tg_cleaner/core/db.py`, `telethon.TelegramClient`, `telethon.errors.FloodWaitError`.
- Produces:
  - `BackupManager`: Creates atomic, timestamped JSON snapshots in `backups/chat_<chat_id>_<timestamp>.json` with message text, media references, entities, and cryptographic checksum. Verifies backup write before allowing deletion.
  - `DeletionExecutor`: Validates user permissions, enforces pre-deletion backup, chunks message IDs into batches of 50-100, applies 1.2s-2.5s jittered delays, traps `FloodWaitError` with automatic sleep, runs dry-run simulation mode, and records results in `deletion_logs`.

- [ ] **Step 1: Write the failing cleaner tests**
Create `tests/test_cleaner.py` verifying backup snapshot file generation, verification of backup integrity, mock Telethon batch deletion with pacing delays, FloodWaitError backoff handling, and dry-run simulation.

- [ ] **Step 2: Run test to verify failure**
Run `pytest tests/test_cleaner.py` to confirm failure.

- [ ] **Step 3: Implement BackupManager**
Implement `src/tg_cleaner/cleaner/backup.py` with JSON serialization, SHA-256 verification, and backup listing.

- [ ] **Step 4: Implement DeletionExecutor**
Implement `src/tg_cleaner/cleaner/executor.py` with batching, jittered delays, FloodWait recovery, and dry-run execution.

- [ ] **Step 5: Run tests and verify pass**
Run `pytest tests/test_cleaner.py` and verify all tests pass.

---

### Task 7: FastAPI Backend & Embedded Local Web Dashboard

**Files:**
- Create: `src/tg_cleaner/web/__init__.py`
- Create: `src/tg_cleaner/web/app.py`
- Create: `src/tg_cleaner/web/routes/api.py`
- Create: `src/tg_cleaner/web/static/index.html`
- Create: `src/tg_cleaner/web/static/app.js`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `fastapi`, `uvicorn`, `starlette.responses.StreamingResponse`, all cleaner subsystems.
- Produces:
  - REST & SSE Endpoints:
    - `GET /api/chats`: List available chats / dialogs.
    - `POST /api/scan`: Trigger chat scan with SSE progress events (`data: {"percent": 45, "status": "Checking duplicates..."}`).
    - `GET /api/results`: Query flagged messages grouped by category with pagination and search.
    - `GET /api/groups/{group_id}/diff`: Retrieve side-by-side diff details for a duplicate group.
    - `POST /api/groups/{group_id}/preset`: Update retention preset for a duplicate group.
    - `POST /api/delete`: Trigger dry-run or live deletion batch with backup creation.
    - `GET /api/backups`: List existing pre-deletion backup archives.
  - Embedded SPA (`index.html` + `app.js`):
    - Clean Tailwind CSS UI with stat cards (Duplicates, Stale Links, Policy Deleted, Storage Saved).
    - Tab navigation (*All*, *Duplicates*, *Stale Links*, *Policy Restricted*).
    - Side-by-side visual diff card for same media/different captions with word-level highlight and preset selector.
    - Multi-select controls (Select All, Deselect, Invert, Category Select).
    - Dry-run simulation toggle and live deletion progress bar.

- [ ] **Step 1: Write the failing web API tests**
Create `tests/test_web.py` using `fastapi.testclient.TestClient` to verify API endpoints (`/api/chats`, `/api/results`, `/api/groups/{id}/diff`, `/api/delete` in dry-run mode, and `/api/backups`).

- [ ] **Step 2: Run test to verify failure**
Run `pytest tests/test_web.py` to confirm failure.

- [ ] **Step 3: Implement Web App and API Routes**
Implement `src/tg_cleaner/web/app.py` and `src/tg_cleaner/web/routes/api.py` connecting the DB, analyzers, backup, and executor.

- [ ] **Step 4: Implement Embedded SPA Frontend**
Implement `src/tg_cleaner/web/static/index.html` and `src/tg_cleaner/web/static/app.js` with responsive layout, Alpine.js reactive state, diff rendering, and SSE stream listeners.

- [ ] **Step 5: Run tests and verify pass**
Run `pytest tests/test_web.py` and verify all tests pass.

---

### Task 8: CLI Entry Point & End-to-End Verification

**Files:**
- Create: `src/tg_cleaner/cli.py`
- Create: `src/tg_cleaner/__main__.py`
- Modify: `pyproject.toml`
- Test: `tests/test_e2e_flow.py`

**Interfaces:**
- Consumes: `typer`, `src/tg_cleaner/web/app.py`, `src/tg_cleaner/core/`.
- Produces:
  - CLI commands:
    - `python -m tg_cleaner web [--port 8000]`
    - `python -m tg_cleaner import-desktop <path_to_result_json>`
    - `python -m tg_cleaner scan <chat_id>`
    - `python -m tg_cleaner clean <chat_id> [--dry-run]`
    - `python -m tg_cleaner backups`
  - Registered console script `tg-cleaner` in `pyproject.toml`.

- [ ] **Step 1: Write E2E flow test**
Create `tests/test_e2e_flow.py` validating the entire sequence: ingest Telegram Desktop JSON fixture -> run all analyzers -> assert same-media/different-caption grouping -> apply preset -> create backup -> execute dry run deletion.

- [ ] **Step 2: Run test to verify failure**
Run `pytest tests/test_e2e_flow.py` to confirm failure.

- [ ] **Step 3: Implement CLI and __main__.py**
Implement `src/tg_cleaner/cli.py` and `src/tg_cleaner/__main__.py` using Typer.

- [ ] **Step 4: Update pyproject.toml**
Update `pyproject.toml` with `tg-cleaner = "tg_cleaner.cli:main"` entry point.

- [ ] **Step 5: Run full test suite and verify 100% pass**
Run `pytest tests/` and verify all tests across all tasks pass cleanly.
