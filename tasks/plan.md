# Implementation Plan: Telegram Archive Cleaner

## Overview
The Telegram Archive Cleaner is a privacy-first, visual audit and cleanup utility for Telegram channels, groups, and Saved Messages. It identifies duplicate messages (exact text, fuzzy text, and same media with different captions), dead HTTP links (404/410/DNS error), expired Telegram chat invite links (`t.me/+...`), and Telegram policy-restricted posts (`restriction_reason`, deleted accounts). It provides an embedded FastAPI single-page dashboard with side-by-side diff previews, smart retention presets, mandatory local JSON backups, and rate-paced batch deletions.

## Architecture Decisions
- **Decoupled Offline Staging:** Messages are extracted once into local SQLite (`cleaner.db`) in WAL mode. All analysis, text hashing, link checking, and diff generation run offline with zero Telegram rate-limit consumption.
- **Remote Relay & Low-Data Mode:** Supports deployment to Railway, behind Cloudflare Tunnels, or routing through SOCKS5/MTProxy relays so users can audit massive archives without consuming local internet data.
- **Zero-Download Media Fingerprinting:** Deduplicates photos and files using Telegram asset IDs (`photo.id`, `document.id`), `(size, mime, duration, dimensions)` tuples, and micro-thumbnails (`thumb=0`) via Pillow perceptual difference hashing (`dHash`).
- **Same Media / Different Captions Engine:** Detects and clusters media with divergent captions, presenting word/character diffs, length deltas, and 4 retention presets (`KEEP_NEWEST`, `KEEP_LONGEST`, `KEEP_OLDEST`, `WHITELIST_ALL`).
- **Ironclad Safety Protocol:** Mandatory pre-deletion JSON backup written to `backups/chat_<chat_id>_<timestamp>.json` with SHA-256 verification before deletion RPCs are allowed; 100-msg batch cap with 1.2s–2.5s jittered delays and automatic `FloodWaitError` recovery.
- **Buildless Embedded Web Dashboard:** FastAPI serves an embedded SPA powered by Tailwind CSS CDN and Alpine.js from `static/`, requiring no Node.js/npm tooling.

---

## Task List

### Phase 1: Foundation & Staging Database (Completed)
- [x] Task 1.1: Database schema, WAL mode, transaction helpers (`src/tg_cleaner/core/db.py`)
- [x] Task 1.2: Data models (`MessageRecord`, `AnalysisFlag`, `DuplicateGroup`, `RetentionPreset`) (`src/tg_cleaner/core/models.py`)
- [x] Task 1.3: Pydantic settings with proxy tuple builder (`src/tg_cleaner/core/settings.py`)
- [x] Task 1.4: Repository cleanup (purged legacy `predoc_pipeline`, obsolete scrapers and databases)
- [x] Task 1.5: Remote relay & cloud deployment configs (`Dockerfile`, `docker-compose.yml`, `railway.toml`, `Procfile`, `tunnel.yml.example`)

### Checkpoint: Foundation
- [x] `pytest tests/test_db.py` passes cleanly (4 passed)

### Phase 2: Perceptual Hashing & Text Utilities
- [ ] Task 2.1: Write unit tests for dHash, Hamming distance, Unicode NFKC normalization, Levenshtein token sorting (`tests/test_hashing.py`)
- [ ] Task 2.2: Implement `src/tg_cleaner/core/hashing.py` with Pillow difference hash and string metrics
- [ ] Task 2.3: Verify all hashing tests pass

### Phase 3: Ingestion Subsystem (Live MTProto & Desktop JSON Export)
- [ ] Task 3.1: Write unit tests with mock Telegram Desktop `result.json` fixture and mock Telethon messages (`tests/test_ingest.py`)
- [ ] Task 3.2: Implement Telegram Desktop parser (`src/tg_cleaner/ingest/desktop_export.py`) handling rich text entity arrays and media refs
- [ ] Task 3.3: Implement Telethon MTProto live iterator (`src/tg_cleaner/ingest/live.py`) with cursor pagination and progress callbacks
- [ ] Task 3.4: Verify ingestion tests pass

### Checkpoint: Ingestion & Staging
- [ ] Test importing both live messages and desktop JSON exports into SQLite

### Phase 4: Deduplication Engine (Exact, Fuzzy & Same Media / Different Captions)
- [ ] Task 4.1: Write unit tests for exact text, fuzzy text, exact media, and same media/different caption grouping (`tests/test_dedupe.py`)
- [ ] Task 4.2: Implement `src/tg_cleaner/analyzer/dedupe.py` with multi-tier media fingerprinting, dHash clustering, and preset resolution
- [ ] Task 4.3: Implement word/character diff generator and metadata summary (`diff_summary`)
- [ ] Task 4.4: Verify deduplication tests pass

### Phase 5: Link Health Checker, Policy Auditor & Stale Content
- [ ] Task 5.1: Write unit tests for HTTP link testing, Telegram invite parsing, policy restrictions, and deleted accounts (`tests/test_analyzers.py`)
- [ ] Task 5.2: Implement async HTTP link checker & Telethon `CheckChatInviteRequest` validator (`src/tg_cleaner/analyzer/links.py`)
- [ ] Task 5.3: Implement temporal cutoff & heuristic date parser (`src/tg_cleaner/analyzer/stale.py`)
- [ ] Task 5.4: Implement Telegram policy restriction & empty media checker (`src/tg_cleaner/analyzer/policy.py`)
- [ ] Task 5.5: Implement optional semantic LLM analyzer for superseded thread messages (`src/tg_cleaner/analyzer/llm.py`)
- [ ] Task 5.6: Verify analyzer tests pass

### Phase 6: Pre-Deletion Backup & Paced Deletion Executor
- [ ] Task 6.1: Write cleaner tests for JSON backup generation, SHA-256 verification, and batch deletion pacing (`tests/test_cleaner.py`)
- [ ] Task 6.2: Implement pre-deletion backup manager (`src/tg_cleaner/cleaner/backup.py`)
- [ ] Task 6.3: Implement paced deletion runner with 100-batch cap, jitter delay, and FloodWait backoff (`src/tg_cleaner/cleaner/executor.py`)
- [ ] Task 6.4: Verify cleaner tests pass

### Phase 7: FastAPI Web Dashboard & Embedded SPA
- [ ] Task 7.1: Write API tests for REST and SSE endpoints (`tests/test_web.py`)
- [ ] Task 7.2: Implement FastAPI backend app & routes (`src/tg_cleaner/web/app.py`, `src/tg_cleaner/web/routes/api.py`)
- [ ] Task 7.3: Implement embedded responsive SPA (`index.html`, `app.js`) with stats cards, category tabs, visual diff cards, and batch deletion controls
- [ ] Task 7.4: Verify web API tests pass

### Phase 8: CLI Entry Point & End-to-End Verification
- [ ] Task 8.1: Write E2E pipeline test covering import -> scan -> dedupe -> diff -> backup -> dry-run deletion (`tests/test_e2e_flow.py`)
- [ ] Task 8.2: Implement Typer CLI (`src/tg_cleaner/cli.py`, `src/tg_cleaner/__main__.py`)
- [ ] Task 8.3: Run entire test suite across all modules and confirm 100% pass

---

## Risks and Mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| Telegram FloodWait on deletion | High | Enforce max 100 IDs per RPC call, 1.2s–2.5s jittered delays, catch `FloodWaitError` and sleep exact `e.seconds + 1` |
| Accidental message loss | Critical | Enforce mandatory pre-deletion JSON archive in `backups/` verified before any delete call; dry-run mode enabled by default |
| High bandwidth on large media | Medium | Zero-download media dedupe using MTProto IDs and micro-thumbnails (`thumb=0`, $< 1\text{ KB}$); support Railway/Cloudflare remote execution |
| Telegram session invalidation | Medium | Graceful error handling in client wrapper with clear re-auth instructions |
