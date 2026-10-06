---
goal: Telegram Archive Cleaner with Multi-Engine Analysis, Cloud Relay Support, and Embedded Web Dashboard
version: 1.0.0
date_created: 2026-10-06
last_updated: 2026-10-06
owner: Amirreza Farnam Taheri
status: 'In progress'
tags: [feature, telegram, cleaner, deduplication, fastapi, telethon, sqlite]
---

# Introduction

![Status: In progress](https://img.shields.io/badge/status-In%20progress-yellow)

The **Telegram Archive Cleaner** is a comprehensive, local-first system designed to audit, categorize, and clean redundant, broken, and policy-restricted messages from any Telegram chat (Saved Messages, broadcast channels, supergroups, or Telegram Desktop `result.json` export files). It features a multi-engine analyzer capable of zero-download media deduplication, same-media/different-caption diffing, asynchronous HTTP dead-link checking, Telegram chat invite testing, mandatory pre-deletion JSON backups, rate-paced batch deletions, and cloud/relay deployment (Railway, Cloudflare Tunnels, SOCKS5/MTProxy) for minimal local internet data usage.

## 1. Requirements & Constraints

- **REQ-001**: Support auditing personal **Saved Messages** (`me`), public/private channels, groups, and supergroups via Telethon MTProto user sessions.
- **REQ-002**: Support offline auditing of Telegram Desktop machine-readable `result.json` export archives.
- **REQ-003**: Detect exact text duplicates via normalized SHA-256 and fuzzy near-duplicates via token sort ratio $\ge 90\%$.
- **REQ-004**: Detect **Same Media / Different Captions** duplicates using zero-download Telegram media asset IDs (`photo.id`, `document.id`), media tuples `(size, mime, duration, dimensions)`, and micro-thumbnail (`thumb=0`) perceptual difference hashing (`dHash`).
- **REQ-005**: Present side-by-side diff comparisons of divergent captions with highlighted additions/deletions and support 4 smart retention presets: `KEEP_NEWEST`, `KEEP_LONGEST`, `KEEP_OLDEST`, and `WHITELIST_ALL`.
- **REQ-006**: Detect stale messages: asynchronous HTTP scanning for HTTP 404/410/DNS errors; validation of Telegram chat invites (`t.me/+...`) without joining via `CheckChatInviteRequest`.
- **REQ-007**: Detect policy-restricted posts (`restriction_reason`), deleted accounts (`is_deleted_sender == True`), and orphaned/empty media (`MessageMediaEmpty`).
- **REQ-008**: Provide an embedded, buildless FastAPI web dashboard powered by Tailwind CSS CDN and Alpine.js with category tabs, search, and batch selection.
- **REQ-009**: Provide a Typer CLI interface for headless server hosting, scanning, and cleaning.
- **SEC-001**: **Zero Data Loss Guarantee**: Create an atomic, verified JSON snapshot in `backups/` containing all message data before executing any deletion RPC.
- **SEC-002**: Never commit or expose Telegram `.session` credentials or message backups.
- **CON-001**: Rate limit deletion RPCs to max 100 message IDs per call with 1.2s–2.5s jittered delays, automatically sleeping on `FloodWaitError`.
- **CON-002**: No Node.js/npm dependencies required to run the local web dashboard.
- **CON-003**: Support low-data mode (`DATA_SAVER_MODE=true`) and cloud relay hosting (Railway, Docker, Cloudflare Tunnel, MTProxy/SOCKS5).
- **PAT-001**: Decoupled SQLite Staging Cache: All messages staged locally before analysis; analysis runs completely offline.

## 2. Implementation Steps

### Implementation Phase 1: Foundation & Staging Database

- GOAL-001: Implement SQLite WAL database manager, Pydantic settings, data models, and clean legacy files.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Implement Settings with proxy tuple builder (`src/tg_cleaner/core/settings.py`) | ✅ | 2026-10-06 |
| TASK-002 | Implement core models for messages, flags, groups, presets (`src/tg_cleaner/core/models.py`) | ✅ | 2026-10-06 |
| TASK-003 | Implement DatabaseManager with WAL mode, indexes, and CRUD (`src/tg_cleaner/core/db.py`) | ✅ | 2026-10-06 |
| TASK-004 | Clean legacy predoc scrapers, build scripts, and test files | ✅ | 2026-10-06 |
| TASK-005 | Add Dockerfile, docker-compose, railway.toml, Procfile, and relay docs | ✅ | 2026-10-06 |
| TASK-006 | Run database unit tests (`tests/test_db.py`) | ✅ | 2026-10-06 |

### Implementation Phase 2: Perceptual Hashing & Text Utilities

- GOAL-002: Implement difference hashing (dHash) and string normalization utilities.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-007 | Write unit tests for dHash, Hamming distance, and normalization (`tests/test_hashing.py`) | | |
| TASK-008 | Implement `src/tg_cleaner/core/hashing.py` with Pillow dHash and Levenshtein token sort fallback | | |
| TASK-009 | Verify `pytest tests/test_hashing.py` passes | | |

### Implementation Phase 3: Ingestion Subsystem

- GOAL-003: Implement Telegram Desktop export parser and Telethon MTProto live message iterator.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-010 | Write ingestion unit tests with mock desktop export and messages (`tests/test_ingest.py`) | | |
| TASK-011 | Implement Telegram Desktop `result.json` parser (`src/tg_cleaner/ingest/desktop_export.py`) | | |
| TASK-012 | Implement Telethon MTProto live iterator with pagination (`src/tg_cleaner/ingest/live.py`) | | |
| TASK-013 | Verify `pytest tests/test_ingest.py` passes | | |

### Implementation Phase 4: Deduplication Engine

- GOAL-004: Implement multi-tier deduplication, same media/different caption clustering, and diff generation.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-014 | Write unit tests for exact, fuzzy, and same media/diff caption duplicates (`tests/test_dedupe.py`) | | |
| TASK-015 | Implement DeduplicationEngine (`src/tg_cleaner/analyzer/dedupe.py`) | | |
| TASK-016 | Implement caption diff generator and retention preset resolution | | |
| TASK-017 | Verify `pytest tests/test_dedupe.py` passes | | |

### Implementation Phase 5: Link, Policy & Stale Content Analyzers

- GOAL-005: Implement async link health checker, Telegram invite tester, policy restriction auditor, and optional LLM pass.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-018 | Write tests for link checking, invite validation, and policy checks (`tests/test_analyzers.py`) | | |
| TASK-019 | Implement async HTTP link checker and invite validator (`src/tg_cleaner/analyzer/links.py`) | | |
| TASK-020 | Implement time decay filter and deadline parser (`src/tg_cleaner/analyzer/stale.py`) | | |
| TASK-021 | Implement policy restriction and empty media auditor (`src/tg_cleaner/analyzer/policy.py`) | | |
| TASK-022 | Implement optional semantic LLM analyzer for superseded thread messages (`src/tg_cleaner/analyzer/llm.py`) | | |
| TASK-023 | Verify `pytest tests/test_analyzers.py` passes | | |

### Implementation Phase 6: Pre-Deletion Backup & Paced Deletion Execution

- GOAL-006: Implement pre-deletion backup snapshots and rate-paced deletion runner.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-024 | Write tests for backup snapshot generation and deletion pacing (`tests/test_cleaner.py`) | | |
| TASK-025 | Implement BackupManager with SHA-256 verification (`src/tg_cleaner/cleaner/backup.py`) | | |
| TASK-026 | Implement DeletionExecutor with 100-msg batch cap and FloodWait recovery (`src/tg_cleaner/cleaner/executor.py`) | | |
| TASK-027 | Verify `pytest tests/test_cleaner.py` passes | | |

### Implementation Phase 7: FastAPI Web Dashboard & Embedded SPA

- GOAL-007: Implement FastAPI backend app, REST & SSE endpoints, and embedded SPA dashboard.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-028 | Write API tests for REST and SSE endpoints (`tests/test_web.py`) | | |
| TASK-029 | Implement FastAPI backend application and routes (`src/tg_cleaner/web/app.py`, `src/tg_cleaner/web/routes/api.py`) | | |
| TASK-030 | Implement embedded responsive SPA (`src/tg_cleaner/web/static/index.html`, `src/tg_cleaner/web/static/app.js`) | | |
| TASK-031 | Verify `pytest tests/test_web.py` passes | | |

### Implementation Phase 8: CLI Entry Point & End-to-End Verification

- GOAL-008: Implement CLI commands and verify end-to-end flow.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-032 | Implement Typer CLI (`src/tg_cleaner/cli.py`, `src/tg_cleaner/__main__.py`) | | |
| TASK-033 | Write end-to-end integration test (`tests/test_e2e_flow.py`) | | |
| TASK-034 | Run full test suite and confirm 100% pass (`pytest tests/`) | | |

## 3. Alternatives

- **ALT-001**: Direct In-Memory Scanning without SQLite Staging. *Rejected*: A crash midway or network disconnect would cause partial, un-resumable state, and repeated analyses would trigger Telegram FloodWaits.
- **ALT-002**: Telegram Bot API instead of Telethon MTProto. *Rejected*: The Bot API cannot access *Saved Messages*, cannot read historical chat logs, and requires manual admin rights in every channel.
- **ALT-003**: External React/Vue Frontend with npm build. *Rejected*: Adds complex Node.js build dependencies to a Python project. An embedded SPA using Tailwind CDN + Alpine.js delivers high responsiveness with zero build setup.

## 4. Dependencies

- **DEP-001**: `telethon >= 1.36.0` (Telegram MTProto client)
- **DEP-002**: `fastapi >= 0.110.0` & `uvicorn >= 0.29.0` (Web server & REST/SSE endpoints)
- **DEP-003**: `pillow >= 10.0.0` (Image processing and dHash calculation)
- **DEP-004**: `httpx >= 0.27.0` (Asynchronous HTTP dead-link scanner)
- **DEP-005**: `pydantic >= 2.7.0` & `pydantic-settings >= 2.3.0` (Data models & settings)
- **DEP-006**: `typer >= 0.12.0` (CLI interface)

## 5. Files

- **FILE-001**: `src/tg_cleaner/core/settings.py` - Configuration and proxy setup
- **FILE-002**: `src/tg_cleaner/core/models.py` - Pydantic data models
- **FILE-003**: `src/tg_cleaner/core/db.py` - SQLite staging database manager
- **FILE-004**: `src/tg_cleaner/core/hashing.py` - Perceptual dHash and text normalization
- **FILE-005**: `src/tg_cleaner/ingest/desktop_export.py` - Telegram Desktop `result.json` parser
- **FILE-006**: `src/tg_cleaner/ingest/live.py` - Telethon live MTProto message iterator
- **FILE-007**: `src/tg_cleaner/analyzer/dedupe.py` - Exact, fuzzy, and same-media/different-caption deduplication
- **FILE-008**: `src/tg_cleaner/analyzer/links.py` - Async HTTP link checker and invite validator
- **FILE-009**: `src/tg_cleaner/analyzer/stale.py` - Time decay and heuristic deadline parser
- **FILE-010**: `src/tg_cleaner/analyzer/policy.py` - Policy restriction and empty media auditor
- **FILE-011**: `src/tg_cleaner/analyzer/llm.py` - Optional semantic LLM analyzer for superseded thread messages
- **FILE-012**: `src/tg_cleaner/cleaner/backup.py` - Pre-deletion JSON backup generator
- **FILE-013**: `src/tg_cleaner/cleaner/executor.py` - Paced batch deletion runner
- **FILE-014**: `src/tg_cleaner/web/app.py` - FastAPI application
- **FILE-015**: `src/tg_cleaner/web/routes/api.py` - REST & SSE API routes
- **FILE-016**: `src/tg_cleaner/web/static/index.html` - Embedded SPA dashboard
- **FILE-017**: `src/tg_cleaner/web/static/app.js` - Reactive UI state and diff viewer
- **FILE-018**: `src/tg_cleaner/cli.py` - Typer CLI entrypoint
- **FILE-019**: `Dockerfile`, `docker-compose.yml`, `railway.toml`, `Procfile` - Cloud relay deployment configs

## 6. Testing

- **TEST-001**: `tests/test_db.py` - Database schema, indexing, and CRUD verification
- **TEST-002**: `tests/test_hashing.py` - dHash, Hamming distance, and text normalization verification
- **TEST-003**: `tests/test_ingest.py` - Desktop JSON export parser and live iterator verification
- **TEST-004**: `tests/test_dedupe.py` - Exact, fuzzy, and same-media/diff-caption deduplication verification
- **TEST-005**: `tests/test_analyzers.py` - Link checking, invite validation, and policy checks verification
- **TEST-006**: `tests/test_cleaner.py` - Pre-deletion backup integrity and deletion pacing verification
- **TEST-007**: `tests/test_web.py` - FastAPI REST & SSE endpoints verification
- **TEST-008**: `tests/test_e2e_flow.py` - End-to-end audit and cleanup pipeline verification

## 7. Risks & Assumptions

- **RISK-001**: Telegram `FloodWaitError` when deleting large quantities of messages. Mitigation: 100-batch cap, 1.2s–2.5s jittered delays, catch `FloodWaitError` and sleep `e.seconds + 1`.
- **RISK-002**: Accidental deletion of valuable messages. Mitigation: Mandatory verified local JSON backup in `backups/` before deletion; dry-run mode enabled by default.
- **ASSUMPTION-001**: User has a Telegram account and can obtain `api_id` and `api_hash` from `my.telegram.org` or has an exported `result.json` from Telegram Desktop.

## 8. Related Specifications / Further Reading

- [docs/TELEGRAM_ARCHIVE_CLEANER_SPEC.md](file:///D:/github/telegram-archive-cleaner/docs/TELEGRAM_ARCHIVE_CLEANER_SPEC.md)
- [docs/DEPLOYMENT_RELAY_GUIDE.md](file:///D:/github/telegram-archive-cleaner/docs/DEPLOYMENT_RELAY_GUIDE.md)
