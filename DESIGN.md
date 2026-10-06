# UI Design

## Main flow

The UI follows five steps:

**Analyze -> Review -> Stage -> Simulate -> Delete**

Analysis only creates results. Nothing is staged automatically. The user chooses what to stage. Simulation creates and verifies a backup without deleting Telegram messages. Live deletion is a separate step with additional confirmation.

## Layout

### Header

Shows the app name, local-service status, refresh, commands, and archive import.

### Archive list

Shows imported or live archive sources. Selecting one loads its analysis results.

### Archive overview

Shows:

- message count;
- last analysis time;
- number of results;
- number ready to stage;
- number that still need approval;
- estimated reclaimable size;
- duplicate and changed-copy counts.

### Review

The Review tab is the default view. It includes:

- search;
- category filters;
- the reason each item was flagged;
- match score where applicable;
- message/media preview;
- approve/reject controls for uncertain results;
- staging controls for approved results.

### Compare

Duplicate groups show the kept message next to other copies. The user can choose one of these retention rules:

- `KEEP_NEWEST`
- `KEEP_LONGEST`
- `KEEP_OLDEST`
- `WHITELIST_ALL`

### Backups

Shows backups that pass the local checksum check. Users can verify, download, or upload a backup copy.

### Connection

Contains:

- optional dashboard API token;
- Telegram API ID/hash;
- phone/code/2FA login;
- optional proxy settings.

## Deletion rules

Live deletion must not rely on browser state alone.

1. The user stages messages.
2. The backend checks that each selected ID is still an active deletion candidate.
3. The app creates a backup containing every selected message.
4. The backup checksum must pass.
5. Live deletion requires an authenticated Telegram session.
6. The user checks the acknowledgement box and types `DELETE N`, where `N` is the staged count.
7. Only then can the deletion request be sent to Telegram.

## Visual rules

### Typography

Use system sans-serif fonts for normal text and the system monospace font for IDs, checksums, timestamps, and byte values.

### Color

- Neutral/slate backgrounds.
- Blue for navigation and ordinary actions.
- Green for successful backup checks and completed states.
- Amber for warnings and items that need attention.
- Red only for staged deletion and live-delete confirmation.

### Components

- Keep card nesting shallow.
- Put message content before analysis details.
- Label the flag reason as plain text such as "Exact duplicate", "Dead link", or "Changed copy".
- Use "Ready to stage" and "Needs approval" instead of vague risk language.
- Show match score as supporting information, not as permission to delete.
- Show the staged-message tray only when at least one item is staged.
- Keep deletion controls out of the normal review path until the user has staged messages.

## Responsive behavior

At narrow widths:

- wrap archive titles;
- stack summary cards;
- reduce media-preview size;
- allow the tab/filter rows to scroll inside their own area;
- keep the five cleanup steps readable;
- never introduce page-level horizontal scrolling.

## Accessibility

- All controls need visible keyboard focus.
- Do not communicate selection or status by color alone.
- Disabled delete actions must look disabled.
- Dialogs need a clear heading, close control, and primary/secondary actions.
- Error text should say what failed: analysis, login, network request, backup, or application state.
- Respect reduced-motion preferences.
- Screenshot checks are not a substitute for keyboard, screen-reader, and contrast testing.

## Copy style

Use short, literal labels. Describe what the app does, not how impressive it is.

Prefer:

- "Backup verified"
- "Needs approval"
- "Local service unavailable"
- "Upload backup"

Avoid promotional adjectives, design jargon, and absolute guarantees.
