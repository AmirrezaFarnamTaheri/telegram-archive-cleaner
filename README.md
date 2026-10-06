# Telegram Archive Cleaner (`tg-cleaner`)

[![CI](https://github.com/AmirrezaFarnamTaheri/telegram-archive-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/AmirrezaFarnamTaheri/telegram-archive-cleaner/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](https://www.python.org/)

Telegram Archive Cleaner reviews Telegram messages for duplicates, changed copies, broken links, stale content, and Telegram restrictions. It can work from a Telegram Desktop `result.json` export or a live Telegram account. The web UI lets you review results, choose what to stage, create a backup, simulate a cleanup, and then delete selected messages if you choose.

## Features

### Duplicate and changed-copy detection

- Exact text matching with normalized SHA-256 hashes.
- Fuzzy text matching for small wording changes.
- Exact media matching when a reliable file identity is available.
- Perceptual image matching with dHash for visually similar images.
- Grouping for the same media posted with different captions.
- Side-by-side caption comparison.
- Retention choices:
  - `KEEP_NEWEST`
  - `KEEP_LONGEST`
  - `KEEP_OLDEST`
  - `WHITELIST_ALL`

Fuzzy and perceptual matches are review results. They are not automatically treated as safe to delete.

### Link and stale-content checks

- Checks HTTP/HTTPS links for common permanent failures such as 404 and 410.
- Checks Telegram invite links with Telethon without joining the target chat.
- Can flag messages older than a configured age.
- Blocks requests to private, loopback, link-local, metadata, and other unsafe network targets. A blocked URL is reported as unverified rather than dead.

### Telegram restrictions and damaged records

- Reports Telegram `restriction_reason` values.
- Reports messages associated with deleted accounts.
- Reports empty or inaccessible media records.

These checks provide review information. They do not by themselves authorize deletion.

### Optional LLM review

The optional LLM analyzer can look for earlier messages that a later message explicitly cancels, replaces, or reschedules. It is disabled unless configured with an API key. Selected message text is sent to the configured provider, so this mode is not local-only. LLM results always require manual approval before they can be staged.

### Backups and deletion

- Nothing is staged automatically.
- The backend re-checks selected message IDs before deletion.
- A JSON backup is created before simulation or live deletion.
- The backup must contain every selected message and pass its SHA-256 check.
- Live deletion requires an authenticated Telegram session and explicit confirmation.
- Telegram deletion requests are split into batches of at most 100 IDs and handle `FloodWaitError` delays.

### Web UI

The FastAPI server includes a single-page web UI with bundled Alpine.js/Tailwind assets and system fonts. No Node.js build step is required.

The main flow is:

**Analyze -> Review -> Stage -> Simulate -> Delete**

The UI also includes duplicate comparison, backup management, Telegram login, proxy settings, and optional API-token protection.

### Remote relay and proxy support

- Optional HTTP relay for external URL checks.
- Railway and Docker deployment files.
- Cloudflare Tunnel configuration examples.
- SOCKS5, HTTP, and MTProxy settings for Telegram connections.

## Quick start

### Install

```bash
git clone https://github.com/AmirrezaFarnamTaheri/telegram-archive-cleaner.git
cd telegram-archive-cleaner

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -e ".[optional,dev]"
```

### Configure

Copy `.env.example` to `.env` and add the settings you need:

```ini
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=your_api_hash_here
TELEGRAM_SESSION_NAME=cleaner_session

# Optional proxy
# TELEGRAM_PROXY_TYPE=socks5
# TELEGRAM_PROXY_HOST=127.0.0.1
# TELEGRAM_PROXY_PORT=1080
```

## Usage

### Web UI

```bash
tg-cleaner web --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

### CLI

```bash
# Import a Telegram Desktop export
tg-cleaner import /path/to/result.json

# Analyze a chat
tg-cleaner scan 123456789

# Create a backup and simulate deletion
tg-cleaner delete 123456789 --dry-run

# Delete the selected current candidates
tg-cleaner delete 123456789 --live

# List recorded backups
tg-cleaner backups
```

### Windows executable

Run `TelegramArchiveCleaner.exe` without arguments to start the local web UI, or pass the same CLI commands shown above.

Build it with:

```powershell
python scripts/build_exe.py
```

The output is written to `dist/TelegramArchiveCleaner.exe`.

## Project layout

```text
telegram-archive-cleaner/
├── src/tg_cleaner/
│   ├── core/                    # Models, settings, database, hashing, network checks
│   ├── ingest/                  # Desktop export and live Telegram import
│   ├── analyzer/                # Duplicate, link, stale, policy, and optional LLM checks
│   ├── cleaner/                 # Backup, cloud upload, and deletion execution
│   ├── web/                     # FastAPI routes and bundled web UI
│   ├── cli.py                   # Typer CLI
│   └── __main__.py
├── relay/                       # Optional relay implementations
├── scripts/                     # Build scripts
├── tests/                       # Unit and integration tests
├── config/                      # Deployment examples
├── Dockerfile
├── docker-compose.yml
└── railway.toml
```

## Tests

```bash
pytest tests/ -v
ruff check src tests scripts
ruff format --check src tests scripts
```

Some tests require the optional development dependencies listed in `pyproject.toml`.

## License

MIT. See [LICENSE](LICENSE).
