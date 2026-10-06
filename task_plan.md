# Task Plan: Telegram Archive Cleaner

**Project:** Telegram Archive Cleaner  
**Repository:** `D:\github\telegram-archive-cleaner`  
**Current Phase:** Phase 8 Completed (Full System Verified)  
**Last Updated:** 2026-10-06  

---

## 1. Goal Statement
Transform the repository into an end-to-end, privacy-respecting Telegram Archive Cleaner application. The system audits any chat (Saved Messages, channels, groups, or Telegram Desktop `result.json` exports), detects duplicates (exact, fuzzy, and **same media with different captions**), flags stale/broken links and policy restrictions, generates verified local JSON backups, and executes rate-paced deletions with a local or remote FastAPI web dashboard.

---

## 2. Core Decisions & Constraints
- **Decoupled Architecture:** Live MTProto and Desktop JSON exports stage messages into local SQLite (`cleaner.db`). All analysis runs offline with zero Telegram API rate consumption.
- **Relay & Cloud Support:** Full support for Railway, Cloudflare Tunnels, Docker, and SOCKS5/MTProxy relays to minimize local internet quota.
- **Zero-Download Media Deduplication:** Media matched via Telegram `photo.id`/`document.id`, `(size, mime, duration, dimensions)` tuples, and micro-thumbnail (`thumb=0`) perceptual difference hashing (`dHash`).
- **Same Media / Different Captions:** Clustered into distinct groups with side-by-side visual diffs, length delta, URL tracking, and 4 smart retention presets (`KEEP_NEWEST`, `KEEP_LONGEST`, `KEEP_OLDEST`, `WHITELIST_ALL`).
- **Ironclad Safety:** Mandatory pre-deletion JSON archive in `backups/` before any deletion RPC; 100-msg batch cap with jittered delay and automatic `FloodWaitError` backoff.

---

## 3. Implementation Phases & Progress

| Phase | Description | Status | Verification Gate |
|---|---|---|---|
| **Phase 1: Foundation & Staging DB** | SQLite WAL staging database, Pydantic settings, proxy config, models, repo cleanup | [x] Complete | `pytest tests/test_db.py` (4 passed) |
| **Phase 2: Perceptual Hashing & Text Proc** | dHash computation (Pillow), Hamming distance, Unicode NFKC normalization, Levenshtein token sorting | [x] Complete | `pytest tests/test_hashing.py` (8 passed) |
| **Phase 3: Ingestion Subsystem** | Telethon MTProto live iterator (`live.py`) & Desktop `result.json` parser (`desktop_export.py`) | [x] Complete | `pytest tests/test_ingest.py` (2 passed) |
| **Phase 4: Deduplication Engine** | Exact text/media dedupe, fuzzy token sort, **same media/different caption** grouping & retention presets | [x] Complete | `pytest tests/test_dedupe.py` (3 passed) |
| **Phase 5: Link, Policy & Stale Analyzers** | Async HTTP link checker (404/410), Telegram invite validator (`CheckChatInviteRequest`), policy restriction auditor, optional LLM pass | [x] Complete | `pytest tests/test_analyzers.py` (4 passed) |
| **Phase 6: Backup & Paced Deletion** | Pre-deletion JSON backup generator with SHA-256 verification, paced batch deletion runner, FloodWait backoff | [x] Complete | `pytest tests/test_cleaner.py` (4 passed) |
| **Phase 7: FastAPI Web Dashboard & UI** | Embedded SPA dashboard (Tailwind + Alpine.js), REST & SSE live scanning endpoints, diff viewer modal | [x] Complete | `pytest tests/test_web.py` (6 passed) |
| **Phase 8: CLI & End-to-End Verification** | Typer CLI (`tg-cleaner web`, `import`, `scan`, `delete`, `backups`), E2E pipeline verification | [x] Complete | `pytest tests/test_cli.py` (2 passed), `pytest tests/test_e2e_flow.py` (1 passed) |

---

## 4. Quality & Compliance Audits
- **Test Suite Status:** 34 passed out of 34 tests in `pytest tests/ -v` (100% pass rate).
- **Code Quality & Linter:** `ruff check src tests` passes with 0 errors.
- **CodeGraph Status:** Fully indexed and synchronized (42 files, 397 nodes, 956 edges).
