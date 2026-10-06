# Findings & Technical Knowledge: Telegram Archive Cleaner

**Project:** Telegram Archive Cleaner  
**Repository:** `D:\github\telegram-archive-cleaner`  
**Last Updated:** 2026-10-06  

---

## 1. Telegram Protocol & Telethon Findings

1. **Bot API vs MTProto User Client:**
   - Telegram Bot API cannot read past chat history, cannot access personal *Saved Messages* (`me`), and requires explicit admin promotion in channels/supergroups.
   - Telethon MTProto User Session provides 100% lifetime read/write access to Saved Messages, channel history via `client.iter_messages`, and low-level flags like `restriction_reason` and `fwd_from`.
2. **Deletion Mechanics & FloodWaits:**
   - Both `channels.deleteMessages` and `messages.deleteMessages` accept up to **100 message IDs** per RPC call.
   - Safe pacing profile: 50–100 messages per call with 1.2s – 2.5s jittered delay.
   - On `FloodWaitError`, Telethon provides `e.seconds`. The cleaner must pause for `e.seconds + 1` before resuming.
3. **Telegram Chat Invite Link Validation:**
   - Invites in format `t.me/+<hash>` or `t.me/joinchat/<hash>` can be inspected without joining via `telethon.functions.messages.CheckChatInviteRequest(hash=...)`.
   - Expired or revoked links trigger `InviteHashExpiredError` or `InviteHashInvalidError`.

---

## 2. Media Deduplication & Same Media / Different Captions

1. **Zero-Download Identity:**
   - Telegram reuses 64-bit integer IDs (`photo.id`, `document.id`) when messages are forwarded or cross-posted.
   - For re-uploaded files, `(file_size, mime_type, duration_seconds, width, height)` matches identical files without byte downloading.
2. **Perceptual Micro-Thumbnail Hashing (dHash):**
   - Telethon allows fetching only the smallest thumbnail: `client.download_media(msg, thumb=0)` transfers $< 1\text{ KB}$ per image.
   - Pillow-based 64-bit difference hash (`dHash`) with Hamming distance $\le 3$ catches re-compressed or resized images reliably.
3. **Same Media / Different Caption Dynamics:**
   - Common in announcement channels (updated event dates, revised links) and Saved Messages (bare saves vs detailed notes).
   - Solution requires visual side-by-side diff cards with word/character additions highlighted, plus 4 smart retention presets:
     - `KEEP_NEWEST` (preserves latest announcement update).
     - `KEEP_LONGEST` (preserves richest notes).
     - `KEEP_OLDEST` (preserves original chronology).
     - `WHITELIST_ALL` (dismisses duplicate flag).

---

## 3. Remote Relay & Cloud Data Optimization

1. **Zero Local Bandwidth Consumption:**
   - When deployed to Railway or behind Cloudflare Tunnels, MTProto queries and HTTP link checks run in the datacenter over gigabit connections.
   - Local user bandwidth is restricted only to the lightweight Web UI HTTP traffic.
2. **In-App MTProto Proxy Support:**
   - Telethon supports SOCKS5, HTTP, and MTProxy configurations directly, routing all MTProto traffic through remote relays even when running locally.
