# Remote Relay & Cloud Deployment Guide (Railway, Cloudflare & Proxies)

This guide documents how to run **Telegram Archive Cleaner** on cloud relays (Railway, VPS, Docker, or behind Cloudflare Tunnels) and configure MTProto relays to maximize scanning speed while minimizing local data/bandwidth consumption.

---

## 1. Why Run on a Cloud Relay?

When auditing large Telegram channels or Saved Messages archives containing thousands of posts:
- **Zero Local Bandwidth Usage**: All MTProto message queries, thumbnail fetching for perceptual hashing, and dead-link HTTP checks occur between the cloud server datacenter and Telegram servers over gigabit connections.
- **Bypasses ISP Throttling / Censorship**: Running on Railway or behind a relay circumvents local internet provider throttling or MTProto blocking.
- **Fast Interactive Web UI**: The user accesses the web dashboard from any browser or phone over lightweight HTTPS, with all heavy processing performed remotely.

---

## 2. Option A: One-Click Deploy to Railway

Railway provides container hosting with automatic HTTPS and persistent volume support.

### Step-by-Step Setup:
1. Fork or push this repository to GitHub.
2. In [Railway.app](https://railway.app), click **New Project** -> **Deploy from GitHub repo**.
3. Railway automatically detects `Dockerfile` and `railway.toml`.
4. Under **Variables**, configure:
   - `TELEGRAM_API_ID`: Your API ID from `my.telegram.org`
   - `TELEGRAM_API_HASH`: Your API Hash from `my.telegram.org`
   - `TELEGRAM_PHONE`: Your phone number (e.g. `+1234567890`)
   - `DATA_SAVER_MODE`: `true`
   - `API_TOKEN`: A secret access token for your dashboard (recommended for public deployments)
5. Under **Settings** -> **Volumes**, mount a persistent volume at `/app/data` and `/app/backups`.
6. Railway assigns a public URL (e.g., `https://tg-cleaner-production.up.railway.app`).

---

## 3. Option B: Cloudflare Tunnel (`cloudflared`) Integration

If running the cleaner on a home server, VPS, or local machine, Cloudflare Tunnel provides:
- **Zero Port Forwarding**: No open firewall ports required.
- **Cloudflare Global Edge Caching & Compression**: Minimizes bandwidth required to load UI assets and message previews.
- **Cloudflare Access (Zero Trust)**: Protect your dashboard with email OTP, Google OAuth, or GitHub login before anyone can access the deletion buttons.

### Setup:
1. Install `cloudflared`:
   ```bash
   # Windows (via winget or choco)
   winget install Cloudflare.cloudflared
   
   # Linux
   sudo apt-get install cloudflared
   ```
2. Authenticate and create a tunnel:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create tg-cleaner
   ```
3. Use the template in `config/cloudflared/tunnel.yml.example`:
   ```yaml
   tunnel: <your-tunnel-id>
   credentials-file: ~/.cloudflared/<your-tunnel-id>.json

   ingress:
     - hostname: cleaner.yourdomain.com
       service: http://localhost:8000
     - service: http_status:404
   ```
4. Start the tunnel:
   ```bash
   cloudflared tunnel run tg-cleaner
   ```

---

## 4. Option C: MTProto Proxy / SOCKS5 Relay (Local or Containerized)

If running locally but you want all Telegram MTProto traffic routed through a high-speed relay or VPN proxy to conserve specific network quotas:
Set in your `.env`:
```env
TELEGRAM_PROXY_TYPE=socks5
TELEGRAM_PROXY_HOST=127.0.0.1
TELEGRAM_PROXY_PORT=1080
# Optional credentials:
TELEGRAM_PROXY_USERNAME=
TELEGRAM_PROXY_PASSWORD=
```
Or for MTProxy:
```env
TELEGRAM_PROXY_TYPE=mtproxy
TELEGRAM_PROXY_HOST=proxy.example.com
TELEGRAM_PROXY_PORT=443
TELEGRAM_PROXY_SECRET=ee1122334455...
```
Telethon connects through the proxy automatically, ensuring Telegram packets route exclusively through the relay.

---

## 5. Bandwidth Saver Mode (`DATA_SAVER_MODE=true`)

When `DATA_SAVER_MODE=true`:
1. **Zero Full-Media Downloads**: Photos, videos, documents, and voice notes are never downloaded.
2. **Metadata-First Deduplication**: Identical files are matched via Telegram `photo.id` / `document.id` or `(file_size, mime_type, duration)` tuples.
3. **Micro-Thumbnails Only**: Only thumbnail index `0` (typically $< 1\text{ KB}$) is downloaded when perceptual hashing is needed for ambiguous photos.
4. **Compressed API Payloads**: FastAPI responses are minimized and paginated to minimize client transfer.
