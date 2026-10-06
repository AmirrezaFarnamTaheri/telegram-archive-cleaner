# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

FastAPI (Python 3.11+) asynchronous backend with SQLite/WAL storage, serving a self-contained, buildless SPA powered by Tailwind CSS and Alpine.js. Zero Node.js build dependencies, zero compile pipelines, instant deployment.

## Users

Telegram channel admins, community archivists, power users managing dense Saved Messages archives, and researchers auditing digital assets across Telegram Desktop JSON exports and live MTProto accounts.

## Product Purpose

Telegram Archive Cleaner provides intelligent visual deduplication, dead-link auditing, and safety-first cleanup. It prevents digital clutter while providing mathematical zero-data-loss guarantees through cryptographically verified SHA-256 pre-deletion snapshots.

## Positioning

Forensic precision and zero data loss. Unlike generic Telegram bots or blind batch-deletion scripts, Telegram Archive Cleaner cross-analyzes exact binary hashes, perceptual image hashes (dHash/pHash), and fuzzy caption similarity. It features a dedicated review engine for "Same Media / Different Captions" (e.g. repeated flyers with updated dates) and delegates link validation to edge relays (Cloudflare Worker / Docker) to protect local bandwidth and IP reputation.

## Operating Context

- Operates locally or inside private Docker/cloud containers.
- Ingests Telegram Desktop export archives (`result.json`) offline without sharing credentials.
- Connects directly to Telegram via MTProto (Phone + Code + 2FA) when live synchronization is desired.
- Offloads external URL checks and media audits to edge relays (Cloudflare Workers or self-hosted Docker proxies) with strict SSRF defense.
- Exports verified JSON rollback snapshots to offsite cloud providers (GitHub Contents API or Google Drive chunked sessions).

## Capabilities and Constraints

- **Multi-Engine Deduplication**: Exact SHA-256, perceptual visual hashing (dHash/pHash), fuzzy caption text MinHash/Jaccard, and cross-caption media matching.
- **Safety First Architecture**: Every batch deletion strictly creates and verifies a pre-deletion JSON snapshot in `backups/` before any message deletion request is dispatched. Dry-run simulation mode verifies safety without touching Telegram.
- **Edge Relay Acceleration**: Zero local bandwidth wasted on dead-link auditing or external media verification.
- **Buildless UI**: Embedded SPA runs directly in any modern browser without npm/vite build steps.

## Brand Commitments

- **Tone & Identity**: Surgical, trustworthy, quiet competence, forensic precision.
- **Visual Discipline**: Strictly zero emojis in code or interface. Standardized geometric SVG icons. High-contrast cockpit palette with subtle status cues.
- **Copy Standard**: Concrete technical language. Direct action verbs. No marketing buzzwords, no vague abstractions.

## Evidence on Hand

- Fully functional unit & integration test suite (`tests/` - 41 tests passing).
- Complete MTProto auth handler and Telegram Desktop JSON parser.
- Working edge relay scripts in `relay/cloudflare/` and `relay/github/`.

## Product Principles

1. **Verify Before Action**: Never delete without an offline, SHA-256 verified rollback snapshot.
2. **Context-Aware Deduplication**: Identical media with changed text requires human-guided retention policies (Keep Newest, Keep Longest, Keep Oldest, Whitelist).
3. **Respect User Bandwidth & Privacy**: Sanitize all outbound requests against SSRF; offload high-traffic URL audits to edge relays.
