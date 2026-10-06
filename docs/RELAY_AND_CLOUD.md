# External Edge Relays & Cloud Storage Integration

Telegram Archive Cleaner can offload bandwidth-heavy operations (dead-link checks, URL header probes, and external media downloads) to an external edge relay, such as a **Cloudflare Worker** or **Railway container**, and export verified pre-deletion archives directly to **Google Drive** or **GitHub**.

---

## 1. Why Use an Edge Relay?

When scanning large Telegram archives containing thousands of external web URLs:
- Probing links locally consumes your personal bandwidth and data caps.
- Local connections may encounter ISP throttling, regional blocks, or DNS timeouts.
- Direct outbound requests could inadvertently probe internal network addresses without strict controls.

By deploying the lightweight streaming relay (`relay/cloudflare/`):
- **Zero local data usage for URL checks**: The edge relay makes the outbound HTTP requests directly from Cloudflare's global edge network.
- **SSRF Protection**: Requests to loopback (`127.0.0.1`), RFC 1918 private subnets, cloud metadata endpoints (`169.254.169.254`), and carrier-grade NAT are rejected before the connection is made.
- **Free tier friendly**: Cloudflare Workers offer 100,000 requests/day at zero cost.

---

## 2. Deploying the Cloudflare Worker Relay

### Prerequisites
- Node.js 18+ and `npm`
- Cloudflare account (free tier)

### Quick Setup

```bash
cd relay/cloudflare
npm install -g wrangler # if not already installed
wrangler login

# Set your secret (must be at least 32 characters)
wrangler secret put RELAY_SHARED_SECRET

# Deploy to Cloudflare edge
wrangler deploy
```

Once deployed, Cloudflare gives you an endpoint URL, for example:
`https://tg-relay.<your-subdomain>.workers.dev`

### Configuring Telegram Archive Cleaner

Add your relay credentials to `.env`:

```env
RELAY_URL="https://tg-relay.<your-subdomain>.workers.dev"
RELAY_SHARED_SECRET="your-secure-32-plus-character-secret"
```

The Web Dashboard will display **Edge Relay: Active (Cloudflare Worker)** in the navigation bar, and all subsequent link audits will automatically route through your edge worker.

---

## 3. Offsite Cloud Export (Google Drive & GitHub)

Before running irreversible message deletions, the cleaner creates an encrypted/hashed local snapshot in `backups/`. You can push these snapshots to offsite cloud storage:

### Export to GitHub Repository
Via API:
```bash
POST /api/backups/<backup_filename>/cloud-export
Content-Type: application/json

{
  "provider": "github",
  "token": "ghp_yourPersonalAccessToken",
  "repo": "your-username/telegram-backups",
  "branch": "main"
}
```

### Export to Google Drive
Via API:
```bash
POST /api/backups/<backup_filename>/cloud-export
Content-Type: application/json

{
  "provider": "google_drive",
  "token": "ya29.yourGoogleOAuthAccessToken",
  "folder_id": "optional-drive-folder-id"
}
```
The export uses Google Drive's **256 KiB aligned resumable streaming protocol** and verifies SHA-256 integrity upon arrival.
