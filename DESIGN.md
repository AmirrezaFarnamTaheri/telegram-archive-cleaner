# DESIGN.md: Telegram Archive Cleaner Data Cockpit

## Strategy & Editorial Positioning

- **Artifact Type**: Forensic Data Cockpit & Archive Curation Suite (Mode: Operate)
- **Positioning**: High-precision forensic tool with cryptographic safety for power users, archivists, and community managers.
- **Brand Adjectives**: Tactical, Forensic, Cryptographic, Uncompromising, Tactile.
- **Aesthetic Essence**: Hardened Forensic Instrument.
- **Audience**: Technical Telegram operators who need to audit dense message histories, remove duplicate media, verify dead links, and preserve restorable snapshots before deletion.
- **Primary Action**: Ingest archive, run multi-engine audit, inspect duplicate differences, and execute safe deletions with verified SHA-256 backup archives.

## Editorial Quality & Anti-Slop Writing Standard

In accordance with `/anti-slop-editorial-quality`, `/humanize`, and `/human-prose`:
- **Zero AI Clichés**: Prohibited words include "delve", "testament", "tapestry", "seamless", "robust", "crucial", "empower", "unlock", "harness", "elevate", "game-changer", "meticulous", "interplay".
- **Zero Marketing Fluff**: Avoid generic superlatives ("Experience the best", "Effortlessly clean"). State concrete mechanisms, byte sizes, exact hash algorithms, status codes, and trade-offs.
- **Zero Structural Staccato**: Informative sentences with natural cadence, direct verbs, and active syntax.
- **Zero Punctuation Tells**: Strictly zero em-dashes and zero en-dashes. Hyphens are used exclusively for compound technical terms (e.g., "dry-run", "pre-deletion").
- **Zero Emojis**: Replaced completely with semantic SVG icons (Lucide / Phosphor technical iconography).

## Typography System

- **Display & Interface Body**: `Plus Jakarta Sans` (Google Fonts / Offline system fallback)
  - Clear geometric forms, optical open counters, high legibility at micro-sizes.
- **Monospace & Numerical Engine**: `JetBrains Mono` (Google Fonts / Offline system fallback)
  - Used for all message identifiers, SHA-256 digests, MIME types, file sizes, and status codes.
  - Tabular numerals enabled via `tabular-nums` for rock-solid grid alignment.
- **Scale (Minor Third, 1.200)**:
  - Header / App Title: 18px (Font weight: 700, tracking: -0.02em)
  - Section Headings: 15px (Font weight: 600, tracking: -0.01em)
  - Primary UI & Body: 13px (Font weight: 500, line-height: 1.5)
  - Secondary Meta: 12px (Font weight: 400, line-height: 1.4)
  - Micro-telemetry: 11px (Font weight: 600, font-mono, tracking: 0.04em, uppercase)

## Color Palette (High-Contrast Obsidian & Technical Signal)

- **Canvas / Background**: `#090d16` (deep dark technical obsidian)
- **Surface Panels**: `#0f172a` (slate 900)
- **Elevated Cards & Containers**: `#131d31` (slate 900 with 4% blue-tint elevation)
- **Hairline Structural Borders**: `#1e293b` (slate 800, 1px)
- **Strong Borders & Dividers**: `#334155` (slate 700)
- **Primary Text**: `#f8fafc` (slate 50, crisp contrast)
- **Secondary Text**: `#94a3b8` (slate 400)
- **Muted Text & Placeholders**: `#64748b` (slate 500)
- **Signal Accents**:
  - Technical Sky (`#0284c7` / `#0ea5e9`): Primary actions, focus rings, active tabs.
  - Tactical Emerald (`#10b981` / `#064e3b`): Verified cryptographic backups, safe items, online status.
  - Signal Amber (`#f59e0b` / `#78350f`): Visual diff variations, broken links, warning thresholds.
  - Alert Rose (`#f43f5e` / `#881337`): Staged deletions, policy restrictions, critical warnings.

## Layout & Component Architecture

1. **Top Cockpit Rail**:
   - Technical title badge with offline standalone detection.
   - Command Palette quick-launcher (`Ctrl+K`).
   - Telemetry status indicators: SQLite database health, MTProto link, Edge Relay proxy.
   - Global workspace actions: Import Desktop JSON, Quick Keyboard Guide (`?`), Sync Refresh.
2. **Left Navigation Sidebar (Collapsible Drawer on Mobile)**:
   - Archive source selector with message counts, storage usage, and last scan timestamps.
   - Quick Demo Sandbox trigger for offline testing.
3. **Central Forensic Workspace**:
   - Target archive metadata banner with quick audit action and staged deletion counter.
   - High-density KPI ribbon (Messages, Exact Dupes, Visual Variations, Dead Links, Restrictions, Reclaimable Bytes).
   - Multi-view tab controller:
     - **Flagged Queue**: Categorized candidate messages, batch selection, keyword filtering, inline rationale.
     - **Diff Studio**: Dual-pane comparative card deck showing identical media with altered captions and retention selectors.
     - **Backup Ledger**: List of cryptographically verified JSON snapshots with SHA-256 hash copying and cloud export.
     - **Forensic Inspector**: Deep JSON inspection of headers, perceptual hashes, and validation traces.
4. **Command Palette (`Ctrl+K`)**:
   - Instant search and keyboard execution of common operations.
5. **Non-Blocking Notification Queue**:
   - Floating toast stack in the lower right for transient success, warning, and error messages.

## Self-Audit Verification

- [x] Zero emojis across all UI copy and code comments.
- [x] Zero em-dashes and zero en-dashes.
- [x] Full offline capability with standalone demo sandbox fallback.
- [x] Clean typographic hierarchy with monospace numbers.
- [x] Full interactive state coverage (hover, focus-visible ring, active scale, disabled).
