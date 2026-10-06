# Architecture

## Overview

Telegram Archive Cleaner imports Telegram messages, stores normalized records in SQLite, runs analysis modules, presents results in a web UI/CLI, creates a backup for selected messages, and can then delete those messages through Telethon.

It supports two input paths:

- Telegram Desktop `result.json` exports;
- live Telegram accounts through MTProto/Telethon.

```text
Telegram export / Telethon
          |
          v
       Ingest
          |
          v
   SQLite (WAL mode)
          |
          +----------------+----------------+----------------+
          |                |                |                |
          v                v                v                v
     duplicates          links           policy           stale/LLM
          \                |                |                /
           +---------------+----------------+---------------+
                                   |
                                   v
                              review results
                                   |
                                   v
                          stage selected items
                                   |
                                   v
                        backup + SHA-256 check
                                   |
                                   v
                         simulate or delete
```

## Modules

### `tg_cleaner.ingest.desktop_export`

Parses Telegram Desktop `result.json` files and stores message IDs, dates, sender data, text, forward/reply information, media metadata, and the original JSON payload.

This path does not require Telegram credentials.

### `tg_cleaner.ingest.live`

Uses Telethon to read Telegram chats through MTProto. It supports incremental reads and stores normalized records in the same database used by desktop imports.

### `tg_cleaner.core.db`

SQLite database manager with WAL enabled. Main tables include:

- `chats`
- `messages`
- `media_hashes`
- `duplicate_groups`
- `analysis_flags`
- `backups`
- `deletion_logs`

Repeated analysis replaces or updates current flags instead of accumulating duplicate rows.

### `tg_cleaner.core.hashing`

Contains text normalization, SHA-256 helpers, image dHash, and similarity utilities.

### `tg_cleaner.core.net_security`

Checks outbound URL targets before requests are made. It rejects loopback, private, link-local, cloud-metadata, carrier-grade NAT, and other disallowed addresses.

A blocked URL is treated as unverified, not dead.

### `tg_cleaner.analyzer.dedupe`

Creates duplicate groups from exact and approximate matches.

Exact matches can be marked ready for staging when the retained copy is known. Fuzzy text and perceptual-image matches stay review-only until approved.

### `tg_cleaner.analyzer.links`

Extracts and checks HTTP/HTTPS links and Telegram invite links. It uses HEAD/GET requests for normal web links and Telethon for Telegram invites.

### `tg_cleaner.analyzer.policy`

Reports Telegram restrictions, deleted senders, and empty/inaccessible media records. These results require review and do not automatically authorize deletion.

### `tg_cleaner.analyzer.stale`

Reports messages that match configured age/deadline rules.

### `tg_cleaner.analyzer.llm`

Optional external review for messages that may have been explicitly superseded by a later message. It sends selected message text to the configured provider. Returned items are always review-only until manually approved.

### `tg_cleaner.cleaner.backup`

Creates a JSON backup for the exact selected message set and verifies its SHA-256 checksum before deletion can continue.

### `tg_cleaner.cleaner.executor`

Sends deletion requests in batches of at most 100 message IDs, adds delay between batches, and waits when Telegram returns `FloodWaitError`.

### `tg_cleaner.cleaner.cloud_export`

Uploads an already verified backup to Google Drive or GitHub when requested.

### `tg_cleaner.web`

FastAPI application and API routes. It serves the bundled Alpine.js/Tailwind web UI and exposes endpoints for imports, analysis, findings, duplicate groups, backups, Telegram login, and deletion.

The API can require `API_TOKEN`. The default server bind address is local-only unless changed by the user.

### `tg_cleaner.cli`

Typer commands for import, analysis, backup listing, web startup, Telegram login, and deletion.

### Packaging and deployment

- `scripts/build_exe.py` and `telegram-archive-cleaner.spec`: Windows executable packaging.
- `Dockerfile` / `docker-compose.yml`: container deployment.
- `railway.toml`: Railway deployment.
- `relay/`: optional external URL-check relay implementations.
