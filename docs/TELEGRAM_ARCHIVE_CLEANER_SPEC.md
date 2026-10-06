# Telegram Archive Cleaner Specification

**Updated:** October 2026

## 1. Scope

Telegram Archive Cleaner reviews Telegram messages before cleanup. It supports:

- Saved Messages;
- private chats;
- groups and supergroups;
- channels available to the authenticated account;
- Telegram Desktop `result.json` exports.

The application can import messages, run analysis, show review results, create backups, simulate deletion, and delete selected live Telegram messages when the account has permission.

## 2. Telegram access

### Bot API

The Bot API is not the primary access method because bots cannot read a user's Saved Messages and cannot request arbitrary history from before they joined a chat.

### MTProto user session

Live access uses Telethon. It can read chats available to the authenticated user and exposes metadata used by the analyzers, including forwarding information, media data, sender state, and Telegram restriction reasons.

Actual read/delete access depends on the account, chat type, permissions, Telegram policy, and server behavior.

## 3. Import

### Desktop export

The importer reads Telegram Desktop `result.json` and stores:

- chat and message IDs;
- timestamps;
- sender information;
- text and text entities;
- reply/forward information;
- media metadata;
- the original payload.

This path works without Telegram credentials.

### Live import

The live importer reads messages through Telethon and writes the same normalized records to SQLite.

## 4. Storage

SQLite runs in WAL mode. Main tables:

- `chats`
- `messages`
- `media_hashes`
- `duplicate_groups`
- `analysis_flags`
- `backups`
- `deletion_logs`

Repeated analysis updates current flags instead of adding duplicate rows. Messages recorded as deleted are not returned to later analysis runs.

## 5. Analysis

### Exact text duplicates

Normalize message text and compare SHA-256 hashes. When a group has a defined retained copy, the other exact copies may be marked ready to stage.

### Similar text

Use fuzzy similarity for messages that differ slightly. Similarity is not proof of duplication, so these results require approval.

### Media matches

Use reliable file identity or hashes where available. Perceptual image hashes may be used to find visually similar images, but those results require review.

File size and MIME type alone must not be treated as exact file identity.

### Same media, different captions

Group messages that share the same media identity but have different text. Show the copies together and let the user choose:

- `KEEP_NEWEST`
- `KEEP_LONGEST`
- `KEEP_OLDEST`
- `WHITELIST_ALL`

### Web links

Extract HTTP/HTTPS links and check them with bounded requests. A 404/410 or confirmed resolution/request failure can be reported as broken according to analyzer rules.

Before a request, validate the destination. Private, loopback, link-local, metadata, carrier-grade NAT, and other blocked addresses are not requested. Blocked targets are reported as unverified.

### Telegram invite links

Check `t.me/+...` and `t.me/joinchat/...` invites through Telethon without joining the target chat.

### Stale-content rules

Optional age/deadline rules can flag older messages. These results require review.

### Telegram restrictions and damaged records

Report:

- `restriction_reason` values;
- deleted senders;
- empty/inaccessible media records.

These are review results and do not automatically authorize deletion.

### Optional LLM review

The LLM analyzer is disabled unless configured with an API key. It sends selected message text to the configured provider and asks only for messages explicitly cancelled, replaced, rescheduled, or superseded by a later message.

LLM results always require manual approval before staging.

## 6. Review states

A result is either:

- **Ready to stage**: current rules allow the item to be selected for cleanup.
- **Needs approval**: the analyzer found something worth reviewing, but the user must approve it before staging.

Nothing is staged automatically.

## 7. Backup and deletion

### Backup

Before simulation or live deletion:

1. Re-check that each requested message is still a current deletion candidate.
2. Read the exact selected message set from the database.
3. Write the backup atomically.
4. Confirm every requested message appears exactly once.
5. Verify the stored SHA-256 against the backup contents.

If any check fails, deletion does not start.

### Simulation

Simulation performs the selection and backup checks but does not call Telegram deletion APIs.

### Live deletion

Live deletion requires:

- an authenticated Telegram session;
- staged current candidates;
- a successful backup;
- user acknowledgement;
- typed `DELETE N` confirmation in the web UI.

Deletion calls are sent in batches of at most 100 message IDs. The executor delays between batches and waits for Telegram `FloodWaitError` durations.

## 8. Web UI

The FastAPI service serves a bundled Alpine.js/Tailwind single-page UI.

Main sections:

- Review
- Compare
- Backups
- Connection

The main sequence is:

**Analyze -> Review -> Stage -> Simulate -> Delete**

The API can require `API_TOKEN`.

## 9. CLI

The Typer CLI covers import, analysis, backup listing, web-server startup, Telegram login, and deletion.

## 10. Relays and cloud backup

External URL checks can optionally use a configured relay. Backups can optionally be uploaded to GitHub or Google Drive.

These features send data to external services and should be enabled only when that tradeoff is acceptable.

## 11. Deployment

Supported deployment files include:

- local Python/uvicorn;
- Windows executable packaging;
- Docker;
- Docker Compose;
- Railway;
- Cloudflare Tunnel examples.

The default local web bind address should remain `127.0.0.1` unless the user intentionally exposes the service.

## 12. Tests

Tests cover storage, hashing, import, analysis, backup/deletion, network target checks, CLI, API routes, cloud upload, and end-to-end behavior.

Run tests with the optional development dependencies installed:

```bash
pytest tests/
```
