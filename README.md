# Telegram Archive Cleaner (tg-cleaner)

[![CI](https://github.com/AmirrezaFarnamTaheri/telegram-archive-cleaner/actions/workflows/ci.yml/badge.svg)](https://github.com/AmirrezaFarnamTaheri/telegram-archive-cleaner/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](https://www.python.org/)

An intelligent, visual Telegram archive auditor and safety-first cleanup system. Designed to audit **Saved Messages (`me`)**, private channels, supergroups, and offline **Telegram Desktop exports (`result.json`)** with multi-engine deduplication, side-by-side visual caption diffing, dead link detection, policy auditing, verifiable pre-deletion backups, and an embedded web dashboard.

---

## Key Features

### 1. Multi-Engine Deduplication & "Same Media / Different Captions"
- **Exact & Fuzzy Deduplication**: Fast SHA-256 content hashing, token sort ratio fuzzy matching, and forwarded message chain tracking.
- **Same Media / Different Captions**: Groups messages sharing the identical media ID or perceptual dHash thumbnail ($Hamming \le 3$) that have differing captions (e.g. rescheduled announcements, updated links, bare saves vs. detailed study notes).
- **Side-by-Side Diff View**: Visual highlighting of caption changes (additions and deletions).
- **Smart Retention Presets**:
  - `KEEP_NEWEST` *(Default)*: Preserves the most recent announcement / update.
  - `KEEP_LONGEST`: Preserves the richest notes / study materials.
  - `KEEP_OLDEST`: Preserves the historical original.
  - `WHITELIST_ALL`: Whitelists all copies, exempting them from deletion.

### 2. Stale Content & Link Health Checker
- **Dead Web Links**: Asynchronous probing (HEAD with GET fallback) detecting HTTP 404, 410, and DNS/network failures.
- **Expired Telegram Invites**: Validates `t.me/+...` and `t.me/joinchat/...` invite links via Telethon's `CheckChatInviteRequest` without joining chats.
- **Temporal Retention**: Flags messages exceeding custom day thresholds.
- **Semantic LLM Audit**: Optional zero-data-leak semantic pass (via Gemini or OpenAI) to identify superseded announcements and expired campaigns.

### 3. Policy & Orphaned Stub Auditor
- **Telegram Platform Restrictions**: Detects posts flagged by Telegram for DMCA copyright or platform terms violations (`restriction_reason`).
- **Deleted Account Senders**: Flags orphaned messages sent by accounts that have since been deleted.
- **Empty / Inaccessible Media**: Identifies damaged or unresolvable media stubs.

### 4. Zero Data Loss Safety Protocol & Paced Deletion
- **Verifiable Pre-Deletion Backups**: Automatically generates a local JSON archive snapshot under `backups/chat_<chat_id>_<timestamp>.json` with SHA-256 payload verification before executing any deletion. If backup verification fails, deletion halts immediately.
- **Batch Capping & Rate Limiting**: Batches requests to $\le 100$ messages per Telegram RPC call, incorporates $1.2\text{s} - 2.5\text{s}$ jittered delay, and handles `FloodWaitError` with automatic exponential backoff.
- **Dry-Run Simulation Mode**: Audits and simulates deletion with verified backups without altering Telegram remote state.

### 5. Embedded Web Dashboard (Zero Node.js Build)
- Built on **FastAPI** serving a modern, responsive single-page application powered by **Tailwind CSS CDN** and **Alpine.js**. No `npm`, `yarn`, or Node.js toolchains required.
- Includes chat overview cards, interactive KPI metrics, category filter tabs, side-by-side comparison cards, and batch deletion controls.

### 6. Cloud Relay & Low-Data Saver Mode
- **Zero Local Bandwidth Consumption**: Pre-configured deployment scripts for **Railway**, **Docker Compose**, and **Cloudflare Tunnels** to run heavy scans and downloads on high-speed datacenter links.
- **Telegram Proxy Support**: Native MTProxy, SOCKS5, and HTTP proxy configuration for restricted network environments.

---

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/AmirrezaFarnamTaheri/telegram-archive-cleaner.git
cd telegram-archive-cleaner

# Create and activate virtual environment (Python 3.11+)
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install package with all dependencies
pip install -e ".[optional,dev]"
```

### 2. Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:
```ini
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=your_api_hash_here
TELEGRAM_SESSION_NAME=cleaner_session

# Optional proxy configuration
# TELEGRAM_PROXY_TYPE=socks5
# TELEGRAM_PROXY_HOST=127.0.0.1
# TELEGRAM_PROXY_PORT=1080
```

---

## Usage

### Standalone Windows Executable (.exe)

Telegram Archive Cleaner can run as a zero-dependency standalone Windows executable that bundles Python, FastAPI backend, deduplication engine, and web static assets:

1. **Interactive Desktop GUI Mode**:
   Double-click `TelegramArchiveCleaner.exe` in Windows Explorer (or run without arguments). It will start the embedded FastAPI server and automatically open your default browser to `http://127.0.0.1:8000`.

2. **Command-Line Interface (CLI) Mode**:
   Run the binary directly in PowerShell or cmd with any Typer CLI command:
   ```powershell
   .\TelegramArchiveCleaner.exe --help
   .\TelegramArchiveCleaner.exe import path\to\result.json
   .\TelegramArchiveCleaner.exe scan 123456789
   .\TelegramArchiveCleaner.exe delete 123456789 --dry-run
   ```

3. **Building the Executable from Source**:
   To compile the `.exe` locally using PyInstaller:
   ```powershell
   python scripts/build_exe.py
   # Output binary located at dist/TelegramArchiveCleaner.exe
   ```

### Web Dashboard (Python Source)

Start the local web dashboard:

```bash
tg-cleaner web --host 0.0.0.0 --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### Command-Line Interface (CLI)

```bash
# 1. Import an offline Telegram Desktop JSON export
tg-cleaner import /path/to/result.json

# 2. Audit a chat (Saved Messages ID or channel ID)
tg-cleaner scan 123456789

# 3. Simulate deletion with dry-run mode (creates verified backup)
tg-cleaner delete 123456789 --dry-run

# 4. Perform live paced deletion
tg-cleaner delete 123456789 --live

# 5. List verified pre-deletion backups
tg-cleaner backups
```

---

## Project Architecture

```
telegram-archive-cleaner/
├── src/tg_cleaner/
│   ├── core/                    # Domain models, database manager, hashing & settings
│   │   ├── models.py            # Pydantic domain models & enums
│   │   ├── db.py                # SQLite staging layer with WAL mode & indexes
│   │   ├── hashing.py           # Perceptual dHash, text normalization, Levenshtein
│   │   └── settings.py          # Environment settings & proxy resolution
│   ├── ingest/                  # Ingestion subsystem
│   │   ├── desktop_export.py    # Telegram Desktop result.json parser
│   │   └── live.py              # Telethon live MTProto cursor iterator
│   ├── analyzer/                # Multi-engine analysis subsystem
│   │   ├── dedupe.py            # Exact & Same-Media Diff-Caption clustering
│   │   ├── links.py             # HTTP 404/DNS and Telegram invite auditor
│   │   ├── policy.py            # Restriction reasons, deleted users & dead stubs
│   │   ├── stale.py             # Temporal retention auditor
│   │   └── llm.py               # Optional semantic superseded analysis
│   ├── cleaner/                 # Safety & execution subsystem
│   │   ├── backup.py            # Pre-deletion JSON snapshots with SHA-256 check
│   │   └── executor.py          # 100-msg batch cap, jitter delays & FloodWait backoff
│   ├── web/                     # Embedded FastAPI delivery layer
│   │   ├── app.py               # FastAPI application factory & static mount
│   │   ├── routes/api.py        # REST endpoints & SSE streaming
│   │   └── static/              # Single-page application (Tailwind + Alpine.js)
│   ├── cli.py                   # Typer CLI commands
│   └── __main__.py              # Python module entry point
├── scripts/
│   └── build_exe.py             # PyInstaller standalone executable compilation script
├── telegram-archive-cleaner.spec# PyInstaller one-file packaging specification
├── tests/                       # Complete automated test suite (43 passing tests)
├── backups/                     # Directory for pre-deletion JSON snapshots
├── config/cloudflared/          # Cloudflare Tunnel configuration templates
├── Dockerfile                   # Multi-stage production container
├── docker-compose.yml           # Local container orchestration
└── railway.toml                 # Railway cloud relay deployment specification
```

---

## Testing & Verification

Run the comprehensive test suite with pytest:

```bash
pytest tests/ -v
```

Check code quality with ruff:

```bash
ruff check src tests scripts
ruff format --check src tests scripts
```

---

## License

This project is licensed under the MIT License.
