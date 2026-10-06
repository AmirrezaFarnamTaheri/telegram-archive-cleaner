# Relays and Cloud Backups

Telegram Archive Cleaner can route external URL checks through a remote relay and can upload verified backup files to GitHub or Google Drive.

These features are optional. Using them sends request or backup data to the configured external service.

## URL-check relay

A relay is useful when:

- you do not want external link checks to originate from your local connection;
- local DNS or ISP filtering interferes with checks;
- you want link-check traffic to run from a remote host.

The relay still receives the target URL, and your client still exchanges request/response data with the relay.

### Network restrictions

The relay rejects requests to disallowed targets such as:

- loopback addresses;
- RFC 1918 private networks;
- link-local addresses;
- cloud metadata endpoints;
- carrier-grade NAT ranges.

These checks reduce SSRF risk but do not make an exposed relay safe without authentication and normal deployment hardening.

## Cloudflare Worker relay

### Requirements

- Node.js 18+
- npm
- a Cloudflare account

### Deploy

```bash
cd relay/cloudflare
npm install -g wrangler
wrangler login
wrangler secret put RELAY_SHARED_SECRET
wrangler deploy
```

Then add the deployed URL and matching secret to `.env`:

```env
RELAY_URL="https://tg-relay.<your-subdomain>.workers.dev"
RELAY_SHARED_SECRET="your-random-secret"
```

The application will send supported external URL checks through that relay.

## Backup upload

Backups are created locally first and must pass their checksum check before upload.

### GitHub

`POST /api/backups/<backup_filename>/cloud-export`

```json
{
  "provider": "github",
  "token": "github-token",
  "repo": "owner/repository",
  "branch": "main"
}
```

### Google Drive

`POST /api/backups/<backup_filename>/cloud-export`

```json
{
  "provider": "google_drive",
  "token": "google-oauth-access-token",
  "folder_id": "optional-folder-id"
}
```

Google Drive uploads use a resumable upload session. GitHub uploads use the Contents API.
