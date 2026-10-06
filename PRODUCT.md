# Product

## Platform

Web UI with CLI support.

## Stack

Python 3.11+, FastAPI, SQLite/WAL, Alpine.js, and bundled Tailwind assets. The web UI is served directly by FastAPI and does not need a Node.js build step.

## Users

People who maintain large Telegram Saved Messages archives, channels, or groups and want help reviewing duplicates, stale posts, broken links, and changed copies before deleting anything.

## Purpose

Telegram Archive Cleaner finds messages that may be redundant or outdated and gives the user a review step before cleanup. It supports Telegram Desktop exports and live MTProto accounts.

Before simulation or live deletion, the app creates a JSON backup containing the selected messages and verifies its SHA-256 checksum. Live deletion also requires Telegram authentication and explicit confirmation.

## Main behavior

- Import `result.json` exports without Telegram credentials.
- Read live Telegram chats through Telethon when credentials are configured.
- Detect exact duplicates, similar text, and same-media/different-caption groups.
- Check web links and Telegram invite links.
- Report Telegram restrictions, deleted senders, and damaged media records.
- Keep uncertain matches as review-only until the user approves them.
- Create and verify a backup before deletion.
- Optionally upload backups to GitHub or Google Drive.
- Optionally route URL checks through a relay.

## UI style

- Direct labels and short explanations.
- System fonts and a restrained dark theme.
- Red is reserved for staged deletion and live-delete confirmation.
- Results explain why an item was flagged.
- Technical terms are used only when they help the user make a decision.
- No promotional claims or absolute recovery guarantees.

## Limits

- A verified backup reduces deletion risk but does not guarantee recovery from every Telegram, filesystem, credential, or external-service failure.
- Fuzzy text, perceptual image, policy, stale-content, and LLM results can be wrong and should be reviewed.
- Remote relays and cloud backup providers receive the data sent to them.
- Live Telegram operations depend on Telegram API availability, account permissions, and rate limits.
