# Deployment and Proxy Guide

This guide covers Railway, Cloudflare Tunnel, and Telegram proxy settings.

## Railway

Railway can run the FastAPI service from the repository Dockerfile.

1. Push or fork the repository to GitHub.
2. Create a Railway project from that repository.
3. Set the variables you need, for example:

```env
TELEGRAM_API_ID=1234567
TELEGRAM_API_HASH=your_api_hash
API_TOKEN=choose-a-secret-token
```

4. Mount persistent storage for the database and backups.
5. Expose the service only after API authentication and any additional access controls are configured.

The app's ASGI entry point is `tg_cleaner.web.app:app`.

## Cloudflare Tunnel

Cloudflare Tunnel can expose a locally running instance without inbound port forwarding.

Install and authenticate `cloudflared`, then create a tunnel:

```bash
cloudflared tunnel login
cloudflared tunnel create tg-cleaner
```

Example configuration:

```yaml
tunnel: <your-tunnel-id>
credentials-file: ~/.cloudflared/<your-tunnel-id>.json

ingress:
  - hostname: cleaner.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Run it with:

```bash
cloudflared tunnel run tg-cleaner
```

If the service is reachable from the public internet, set `API_TOKEN` and consider an additional access layer such as Cloudflare Access.

## Telegram proxy settings

Telegram traffic can use SOCKS5, HTTP, or MTProxy settings.

### SOCKS5

```env
TELEGRAM_PROXY_TYPE=socks5
TELEGRAM_PROXY_HOST=127.0.0.1
TELEGRAM_PROXY_PORT=1080
TELEGRAM_PROXY_USERNAME=
TELEGRAM_PROXY_PASSWORD=
```

### MTProxy

```env
TELEGRAM_PROXY_TYPE=mtproxy
TELEGRAM_PROXY_HOST=proxy.example.com
TELEGRAM_PROXY_PORT=443
TELEGRAM_PROXY_SECRET=ee1122334455...
```

The proxy changes the route used by the Telegram client. It does not remove normal bandwidth use between the application and the proxy.

## Data-saver mode

When `DATA_SAVER_MODE=true`, the application avoids full-media downloads where possible and prefers Telegram metadata or small thumbnails for matching. Approximate metadata matches must not be treated as proof that two files are identical.
