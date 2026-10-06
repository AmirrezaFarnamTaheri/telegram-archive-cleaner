# DESIGN.md: Telegram Archive Cleaner

## Context (from discovery)

- **Artifact type**: Dashboard / Data Forensic Tool (Mode: `Operate`)
- **Positioning**: Technical, Utilitarian, Forensic
- **Audience**: Power Telegram users, channel administrators, and digital archivists.
- **Primary action**: Run audit, inspect duplicates with perceptual certainty, and execute safe deletions with verified SHA-256 rollback backups.
- **Brand Adjectives**: Surgical, Trustworthy, Uncluttered, Fast, Cryptographically-Safe.
- **Visual Word Translations**:
  - *Surgical*: 1px hairline borders, monospaced tabular data, tight functional spacing, zero ornamental flairs.
  - *Trustworthy*: Prominent SHA-256 checksum displays, non-destructive dry-run defaults, explicit safety alerts.
  - *Uncluttered*: Cockpit telemetry strip, categorized filter pills, side-by-side diffing cards, strictly zero emojis.
  - *Fast*: Buildless client runtime, sub-150ms state transitions, keyboard shortcuts (Esc to close modals).
  - *Cryptographically-Safe*: Explicit hash verification badges, persistent backup history table with one-click offsite cloud export.
- **Aesthetic Essence (3 words)**: Precision Archive Forensic.
- **Single-minded Proposition**: Complete clarity and cryptographic safety in Telegram archive curation.
- **Mode**: Dark (Cockpit / OLED-friendly).
- **Density**: Dense (Cockpit mode with high scanability and tabular numerals).
- **Constraints**: Pure HTML5/Tailwind/Alpine.js delivered directly by FastAPI. Zero Node.js build pipeline.

## Aesthetic

- **Direction**: Precision Dark Technical Cockpit.
- **Defining Trait**: High-density telemetry combined with 1px hairline structural frames and monospaced cryptographic identifiers.
- **Signature Move**: Side-by-side visual duplicate cards with live media thumbnails, character-level diff highlighting, and instant retention policy toggles (Keep Newest, Keep Longest, Whitelist).

## Typography

- **Display & Body**: `Plus Jakarta Sans` | Source: Google Fonts | License: OFL
  - High geometric clarity, optical legibility at 11px-14px micro-sizes, wide aperture.
- **Monospace & Numerical**: `JetBrains Mono` | Source: Google Fonts | License: Apache 2.0
  - Tabular numerals (`font-variant-numeric: tabular-nums`), message IDs, SHA-256 checksums, byte calculations.
- **Type Scale** (Base: 14px, Ratio: 1.2 Minor Third):
  - Hero/Header: 20px (weight 700, tracking -0.02em)
  - Section Title: 16px (weight 600, tracking -0.01em)
  - Card/Body: 14px (weight 400/500, line-height 1.5)
  - Caption/Meta: 12px (weight 400/500, line-height 1.4)
  - Micro-telemetry: 11px (weight 600, uppercase, tracking 0.05em)
- **Tracking & Measure**:
  - Display tracking: `-0.02em` to `-0.03em`.
  - Content measure: Max `70ch` per caption block.

## Color System

- **Strategy**: Deep slate canvas with high-contrast signal accents. Replaces the statistical median "AI purple gradient" with an industrial palette of Obsidian (`#090d16`), Slate (`#0f172a`), Cyan (`#0284c7`), Emerald (`#10b981`), Amber (`#f59e0b`), and Rose (`#f43f5e`).
- **Distribution**: 65% Neutral Surface / 25% Slate Frame / 10% Functional Signal.
- **Palette Tokens**:
  - Canvas / Background: `#090d16` (deep dark slate)
  - Surface Elevation 1: `#0f172a` (slate-900)
  - Surface Elevation 2 (Card/Container): `#131d31` (slate-900/80)
  - Border Hairline: `#1e293b` (slate-800)
  - Border Subtle: `#334155` (slate-700)
  - Text Primary: `#f8fafc` (slate-50)
  - Text Secondary: `#94a3b8` (slate-400)
  - Text Muted: `#64748b` (slate-500)
  - Brand Primary / Focus Accent: `#0ea5e9` (sky-500) / `#0284c7` (sky-600)
  - Success / Preserved: `#10b981` (emerald-500) / `#064e3b` (surface)
  - Warning / Policy / Duplicate: `#f59e0b` (amber-500) / `#78350f` (surface)
  - Danger / Deletion Target: `#f43f5e` (rose-500) / `#881337` (surface)

## Spacing, Radius, Shadow

- **Base Unit**: 4px (spacing scale: 4, 8, 12, 16, 20, 24, 32px).
- **Radius**: Max two levels: `6px` (`rounded-md`) for controls and badges; `10px` (`rounded-lg`) for panels and modal windows. No generic 24px+ blob rounding.
- **Shadow & Depth**: 1px structural borders are the primary elevation mechanism. Soft elevation shadow (`shadow-2xl shadow-black/80`) is reserved strictly for modal viewports and toast notifications.

## Layout and Composition

- **Global Framework**: Fixed sticky top cockpit bar (header) + 2-column layout (72-width chat navigation sidebar + full-width fluid analytical workspace).
- **Telemetry Bar**: 7-point dense KPI ribbon displaying Total Messages, Exact Dupes, Same Media Diff, Dead Links, Policy Flags, Deletion Candidates, and Reclaimable Bytes in tabular monospace numbers.
- **Candidate Filter Ribbon**: Quick filter chips (`All`, `Exact Dupes`, `Same Media`, `Dead Links`, `Policy`) + instantaneous keyword search bar.
- **Responsive Handling**: Mobile and small displays collapse the sidebar into an accessible drawer toggle with `overflow-x-auto` wrappers for data tables.

## Components and States

- **Buttons**:
  - Primary (Filled): High contrast sky/rose/emerald with `:active:scale-[0.98]` tactile depression and smooth hover transitions.
  - Secondary (Framed): Slate border with subtle light wash on hover.
  - Focus Ring: `focus-visible:ring-2 focus-visible:ring-sky-500 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 focus-visible:outline-none`.
- **Inputs**: Explicit text label above input, dark mono styling for tokens/phone, keyboard Enter submission handler.
- **Modals**: ESC-to-close handler, click-backdrop-to-dismiss, backdrop blur, trapped focus, smooth opacity fade.
- **Toast Notifications**: Replaces intrusive browser `alert()` popups with a floating non-blocking notification queue in the lower-right corner (auto-dismissing with manual close action).
- **Zero-Emoji Discipline**: Emojis are strictly banned. Replaced by semantic SVG icons from Lucide/Phosphor style definitions (Lightning, Shield, Cross, Arrow, Folder, Checkmark, Refresh).

## Motion & Interaction

- **Duration**: Fast (150ms-200ms) for buttons and tabs; 250ms for modal backdrops.
- **Easing**: `cubic-bezier(0.16, 1, 0.3, 1)` (snappy ease-out).
- **Reduced Motion**: Respects `@media (prefers-reduced-motion: reduce)` with instantaneous transitions.

## Slop Self-Audit Checklist

- [x] No generic AI fonts: `Plus Jakarta Sans` and `JetBrains Mono` imported and configured.
- [x] No generic AI purple/violet gradients: Replaced with high-contrast Obsidian/Slate + precision Sky/Emerald/Rose cues.
- [x] Zero emojis in code or user interface: 100% replaced with standardized SVG icons.
- [x] No browser `alert()` dialogs: Replaced with an elegant in-app toast notification system.
- [x] Full interactive state coverage: default, hover, active tactile scale, focus rings, disabled, and loading spinners.
- [x] Tabular data alignment: All numeric counters, byte sizes, message IDs, and SHA-256 hashes render in monospace tabular numerals.
- [x] Accessibility: Keyboard operability, explicit form labels, contrast ratio exceeding WCAG 2.2 AA (4.5:1 minimum).
