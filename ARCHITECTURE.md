# Architecture: Telegram Archive Cleaner

## 1. System Overview

Telegram Archive Cleaner (`tg-cleaner`) is an offline-capable, safety-first audit and deletion engine for Telegram archives. It audits Saved Messages, private channels, supergroups, and offline Telegram Desktop export archives (`result.json`).

The system identifies exact duplicate messages, same-media messages with differing captions, dead web hyperlinks, expired Telegram invitation links, policy restrictions, and orphaned stubs from deleted accounts. Before any destructive operation occurs, the system mandates a verified local backup archive.

```
                      +---------------------------------------+
                      |         Archive Ingestion             |
                      |  - MTProto Client (Telethon)          |
                      |  - Desktop Export Parser (result.json)|
                      +-------------------+-------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |       SQLite WAL Store (cleaner.db)   |
                      |  - Messages & Raw Payloads            |
                      |  - Media Metadata & Perceptual Hashes |
                      |  - Safety Ledger & Candidate Indexes  |
                      +-------------------+-------------------+
                                          |
        +---------------------------------+---------------------------------+
        |                                 |                                 |
        v                                 v                                 v
+-----------------------+     +-----------------------+     +-----------------------+
|  Deduplication Engine |     |  Link & Policy Engine |     |  Safety & Backup Core |
|  - SHA-256 Content    |     |  - Async HTTP Prober  |     |  - Pre-deletion JSON  |
|  - Token Sort Fuzzy   |     |  - SSRF Guardrails    |     |  - SHA-256 Integrity  |
|  - Perceptual dHash   |     |  - Invite Link Verif. |     |  - Paced Deletion     |
|  - Same-Media Diff    |     |  - Restricted Posts   |     |  - Cloud Export S3    |
+-----------------------+     +-----------------------+     +-----------------------+
        |                                 |                                 |
        +---------------------------------+---------------------------------+
                                          |
                                          v
                      +---------------------------------------+
                      |      Operator Interfaces              |
                      |  - CLI Interface (Typer)              |
                      |  - Web Cockpit (FastAPI + Alpine.js)  |
                      |  - Standalone Executable (PyInstaller)|
                      +---------------------------------------+
```

---

## 2. Component Architecture

### 2.1 Ingestion Layer

The ingestion layer normalizes incoming message streams into uniform message schemas.

1. **Desktop Export Parser (`tg_cleaner.ingest.desktop_export`)**:
   - Parses official Telegram Desktop `result.json` export files.
   - Extracts message identifiers, ISO 8601 timestamps, sender details, text tokens, reply chains, forwarded origins, and file attachments.
   - Operates entirely offline without requiring Telegram API keys or network sockets.

2. **MTProto Live Synchronizer (`tg_cleaner.ingest.live`)**:
   - Connects to Telegram core servers via Telethon over MTProto.
   - Supports user accounts (`Saved Messages`, private groups, channels) and bot tokens.
   - Implements sequential message retrieval with checkpoint markers to resume interrupted synchronization runs.

### 2.2 Storage Layer

The storage layer provides ACID guarantees and resilient persistence.

- **Engine (`tg_cleaner.core.db`)**: SQLite with Write-Ahead Logging (WAL) enabled (`PRAGMA journal_mode=WAL`).
- **Storage Path Fallback**: Defaults to `data/cleaner.db`. If filesystem write permissions are denied in the working directory, the database automatically initializes under `%LOCALAPPDATA%/tg_cleaner/data/cleaner.db` on Windows or `~/.local/share/tg_cleaner/data/cleaner.db` on POSIX environments.
- **Tables**:
  - `chats`: Chat records, title, type, and synchronization checkpoints.
  - `messages`: Normalized message attributes, timestamps, sender IDs, forwarding metadata, and raw JSON payloads.
  - `media_hashes`: Precomputed SHA-256 binary digests and perceptual difference hashes (dHash).
  - `deletion_candidates`: Candidate records flagged for review with reason codes and retention designations.
  - `backups`: Pre-deletion backup ledger records with file paths and SHA-256 checksums.

### 2.3 Analysis & Deduplication Engines

The analysis tier uses multi-stage inspection to categorize target messages without data loss.

1. **Exact & Fuzzy Deduplication (`tg_cleaner.analyzer.dedupe`)**:
   - Matches identical text payloads using normalized SHA-256 hashing.
   - Computes RapidFuzz token sort ratios for minor variations.
   - Groups forwarded message chains sharing origin message IDs.

2. **Same-Media Different-Caption Analysis**:
   - Evaluates media assets using exact file hashes or 64-bit perceptual dHash values (Hamming distance threshold <= 3).
   - Identifies instances where an identical image or document is shared across multiple messages with updated text or notes.
   - Offers retention designations: `KEEP_NEWEST`, `KEEP_LONGEST`, `KEEP_OLDEST`, and `WHITELIST_ALL`.

3. **Link Health Prober (`tg_cleaner.analyzer.links`)**:
   - Extracts HTTP and HTTPS URIs from message bodies and entity attributes.
   - Issues asynchronous HEAD probes with automatic GET fallback to detect HTTP 404, 410, and DNS resolution failures.
   - Inspects `t.me/+...` and `t.me/joinchat/...` invite links using Telethon `CheckChatInviteRequest` without joining target chats.

4. **Network Security & SSRF Protection (`tg_cleaner.core.net_security`)**:
   - Validates target link destinations before making network requests.
   - Blocks requests to loopback addresses, private RFC 1918 subnets, carrier-grade NAT blocks, cloud metadata IP addresses (`169.254.169.254`), and link-local ranges.
   - Supports routing external probes through isolated edge relay proxies.

5. **Policy & Stub Auditor (`tg_cleaner.analyzer.policy`)**:
   - Detects messages flagged by Telegram for platform or copyright restrictions (`restriction_reason`).
   - Identifies orphaned messages sent by deleted accounts (`Deleted Account`).
   - Identifies empty media envelopes and damaged attachments.

### 2.4 Safety Protocol & Paced Deletion

Destructive actions are guarded by strict verification steps.

1. **Verifiable Pre-Deletion Backup (`tg_cleaner.cleaner.backup`)**:
   - Before any message deletion, extracts all candidate records into a standalone JSON backup archive under `backups/chat_<chat_id>_<timestamp>.json`.
   - Computes SHA-256 checksum of the serialized payload and records it in the database ledger.
   - Verifies the backup on disk immediately after creation. If verification fails, the operation aborts before deleting any remote content.

2. **Paced Execution (`tg_cleaner.cleaner.executor`)**:
   - Batches deletion calls in increments capped at 100 message IDs.
   - Introduces randomized jitter delays (1.2 to 2.5 seconds) between calls.
   - Traps Telegram `FloodWaitError` responses and sleeps for the required duration plus one second.

3. **Cloud Export (`tg_cleaner.cleaner.cloud_export`)**:
   - Optionally transfers local backup archives to external S3-compatible object stores or WebDAV targets before deletion.

### 2.5 Presentation & Operator Interfaces

1. **Command-Line Interface (`tg_cleaner.cli`)**:
   - Built on Typer with Rich terminal output.
   - Provides commands for `login`, `sync`, `import`, `scan`, `delete`, `backups`, and `web`.

2. **Embedded Web Cockpit (`tg_cleaner.web`)**:
   - FastAPI asynchronous server serving a buildless client-side SPA.
   - Uses Alpine.js for reactive state and Tailwind CSS for utility styling.
   - Includes a Command Palette (`Ctrl+K`), visual diff studio for captions, telemetry ribbon, raw message JSON inspector, and full offline mock sandbox mode.

3. **Standalone Desktop Executable (`scripts/build_exe.py`)**:
   - Packages the application into a single self-contained Windows executable (`dist/TelegramArchiveCleaner.exe`) via PyInstaller.
   - Bundles all required static web assets and schemas for offline operation.
