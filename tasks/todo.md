# Task Checklist: Telegram Archive Cleaner

## Phase 1: Foundation & Staging Database
- [x] **TASK-001**: Implement Pydantic settings with proxy support (`src/tg_cleaner/core/settings.py`)
- [x] **TASK-002**: Implement data models (`src/tg_cleaner/core/models.py`)
- [x] **TASK-003**: Implement SQLite DatabaseManager with WAL mode (`src/tg_cleaner/core/db.py`)
- [x] **TASK-004**: Clean obsolete legacy files from repository
- [x] **TASK-005**: Create remote relay and cloud deployment stack (`Dockerfile`, `docker-compose.yml`, `railway.toml`, `Procfile`, `docs/DEPLOYMENT_RELAY_GUIDE.md`)
- [x] **TASK-006**: Verify database unit tests pass (`tests/test_db.py`)

## Phase 2: Perceptual Hashing & Text Utilities
- [ ] **TASK-007**: Write unit tests for dHash, Hamming distance, and text normalizer (`tests/test_hashing.py`)
- [ ] **TASK-008**: Implement Pillow-based difference hashing and Levenshtein token sort fallback (`src/tg_cleaner/core/hashing.py`)
- [ ] **TASK-009**: Verify `pytest tests/test_hashing.py` passes

## Phase 3: Ingestion Subsystem
- [ ] **TASK-010**: Write ingestion unit tests for Desktop export and MTProto messages (`tests/test_ingest.py`)
- [ ] **TASK-011**: Implement Telegram Desktop `result.json` parser (`src/tg_cleaner/ingest/desktop_export.py`)
- [ ] **TASK-012**: Implement Telethon MTProto live message iterator (`src/tg_cleaner/ingest/live.py`)
- [ ] **TASK-013**: Verify `pytest tests/test_ingest.py` passes

## Phase 4: Deduplication Engine (Exact, Fuzzy & Same Media / Different Captions)
- [ ] **TASK-014**: Write tests for exact text, fuzzy, and same media/different caption scenarios (`tests/test_dedupe.py`)
- [ ] **TASK-015**: Implement DeduplicationEngine with multi-tier media grouping (`src/tg_cleaner/analyzer/dedupe.py`)
- [ ] **TASK-016**: Implement inline caption diff generator and retention presets (`src/tg_cleaner/analyzer/dedupe.py`)
- [ ] **TASK-017**: Verify `pytest tests/test_dedupe.py` passes

## Phase 5: Link, Policy & Stale Content Analyzers
- [ ] **TASK-018**: Write tests for HTTP link testing, invite validation, policy flags, and deleted senders (`tests/test_analyzers.py`)
- [ ] **TASK-019**: Implement async HTTP link checker and Telethon invite validator (`src/tg_cleaner/analyzer/links.py`)
- [ ] **TASK-020**: Implement stale cutoff and deadline parser (`src/tg_cleaner/analyzer/stale.py`)
- [ ] **TASK-021**: Implement policy restriction and empty media auditor (`src/tg_cleaner/analyzer/policy.py`)
- [ ] **TASK-022**: Implement optional semantic LLM analyzer for superseded thread messages (`src/tg_cleaner/analyzer/llm.py`)
- [ ] **TASK-023**: Verify `pytest tests/test_analyzers.py` passes

## Phase 6: Pre-Deletion Backup & Paced Deletion Execution
- [ ] **TASK-024**: Write unit tests for JSON backup generation and batch deletion pacing (`tests/test_cleaner.py`)
- [ ] **TASK-025**: Implement BackupManager with SHA-256 verification (`src/tg_cleaner/cleaner/backup.py`)
- [ ] **TASK-026**: Implement DeletionExecutor with 100-msg batch cap, jitter delays, and FloodWait backoff (`src/tg_cleaner/cleaner/executor.py`)
- [ ] **TASK-027**: Verify `pytest tests/test_cleaner.py` passes

## Phase 7: FastAPI Web Dashboard & Embedded SPA
- [ ] **TASK-028**: Write API tests for REST and SSE endpoints (`tests/test_web.py`)
- [ ] **TASK-029**: Implement FastAPI backend application and routes (`src/tg_cleaner/web/app.py`, `src/tg_cleaner/web/routes/api.py`)
- [ ] **TASK-030**: Implement embedded SPA frontend (`src/tg_cleaner/web/static/index.html`, `src/tg_cleaner/web/static/app.js`)
- [ ] **TASK-031**: Verify `pytest tests/test_web.py` passes

## Phase 8: CLI Entry Point & End-to-End Verification
- [ ] **TASK-032**: Implement Typer CLI (`src/tg_cleaner/cli.py`, `src/tg_cleaner/__main__.py`)
- [ ] **TASK-033**: Write end-to-end integration test (`tests/test_e2e_flow.py`)
- [ ] **TASK-034**: Verify entire test suite passes (`pytest tests/`)
