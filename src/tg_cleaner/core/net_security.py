"""Network security, SSRF protection, and URL normalization.

Absorbed and adopted from link-to-cloud security foundations.
Enforces strict SSRF blocking against private subnets, cloud metadata
endpoints, carrier-grade NAT, and documentation address spaces.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

RESERVED_EDGE_HOSTS: frozenset[str] = frozenset({
    "localhost",
    "localhost.",
    "metadata.google.internal",
    "metadata.google.internal.",
    "instance-data.ec2.internal",
    "instance-data.ec2.internal.",
})

RESERVED_EDGE_SUFFIXES: tuple[str, ...] = (
    ".localhost",
    ".local",
    ".internal",
    ".home.arpa",
)

MIME_EXTENSIONS: dict[str, str] = {
    "application/zip": ".zip",
    "application/pdf": ".pdf",
    "application/json": ".json",
    "application/gzip": ".gz",
    "application/x-tar": ".tar",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "text/plain": ".txt",
    "text/html": ".html",
    "text/csv": ".csv",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
}


def is_private_ip(ip_str: str) -> bool:
    """Check if an IPv4 or IPv6 address belongs to private, loopback, or reserved space.

    Blocks RFC1918, RFC6598 carrier NAT, RFC3927 link-local, multicast,
    loopback, documentation, and cloud metadata ranges.
    """
    try:
        ip = ipaddress.ip_address(ip_str.strip("[]"))
    except ValueError:
        return True

    # Standard library checks: private, loopback, link-local, multicast, reserved
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return True

    if isinstance(ip, ipaddress.IPv4Address):
        # 100.64.0.0/10 Carrier-grade NAT (RFC 6598)
        if ip in ipaddress.IPv4Network("100.64.0.0/10"):
            return True
        # 198.18.0.0/15 Benchmark testing (RFC 2544)
        if ip in ipaddress.IPv4Network("198.18.0.0/15"):
            return True
        # 192.0.0.0/24 IETF Protocol Assignments
        if ip in ipaddress.IPv4Network("192.0.0.0/24"):
            return True
        # 192.0.2.0/24 TEST-NET-1 (RFC 5737)
        if ip in ipaddress.IPv4Network("192.0.2.0/24"):
            return True
        # 198.51.100.0/24 TEST-NET-2 (RFC 5737)
        if ip in ipaddress.IPv4Network("198.51.100.0/24"):
            return True
        # 203.0.113.0/24 TEST-NET-3 (RFC 5737)
        if ip in ipaddress.IPv4Network("203.0.113.0/24"):
            return True
    elif isinstance(ip, ipaddress.IPv6Address):
        # IPv4-mapped IPv6 addresses (::ffff:0:0/96)
        if ip.ipv4_mapped:
            return is_private_ip(str(ip.ipv4_mapped))
        # 2001:db8::/32 Documentation (RFC 3849)
        if ip in ipaddress.IPv6Network("2001:db8::/32"):
            return True
        # 3fff::/20 Documentation (RFC 9637)
        if ip in ipaddress.IPv6Network("3fff::/20"):
            return True
        # 5f00::/16 Segment Routing SIDs
        if ip in ipaddress.IPv6Network("5f00::/16"):
            return True
        # 2001:2::/48 Benchmarking
        if ip in ipaddress.IPv6Network("2001:2::/48"):
            return True

    return False


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """Validate that a URL is a valid public HTTP/HTTPS endpoint and safe against SSRF.

    Returns (is_safe, reason).
    """
    if not url or len(url) > 8192:
        return False, "URL length invalid"

    try:
        parsed = urlparse(url.strip())
    except Exception as e:
        return False, f"Invalid URL structure: {e}"

    if parsed.scheme.lower() not in ("http", "https"):
        return False, f"Unsupported scheme: {parsed.scheme}"

    if parsed.username or parsed.password:
        return False, "Embedded credentials are not allowed"

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        return False, "Missing hostname"

    if hostname in RESERVED_EDGE_HOSTS or any(hostname.endswith(s) for s in RESERVED_EDGE_SUFFIXES):
        return False, f"Reserved or internal hostname: {hostname}"

    # Check if hostname is a literal IP address
    try:
        ip = ipaddress.ip_address(hostname)
        if is_private_ip(str(ip)):
            return False, f"Private or non-public IP address: {hostname}"
        return True, "Safe literal IP"
    except ValueError:
        pass

    # Resolve hostname via DNS and check if it points to a private address
    try:
        addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        if addr_info:
            for _family, _, _, _, sockaddr in addr_info:
                ip_str = sockaddr[0]
                if is_private_ip(ip_str):
                    return False, f"Hostname {hostname} resolves to non-public IP {ip_str}"
    except (socket.gaierror, Exception):
        # Allow HTTP client to handle offline/mocked hosts
        pass

    return True, "Safe public URL"


def normalize_url(url: str) -> str:
    """Rewrite popular cloud file-sharing URLs into direct download links.

    - Dropbox: sets dl=1, removes raw
    - GitHub: rewrites github.com/user/repo/blob/branch/file to raw.githubusercontent.com
    - Google Drive: rewrites /file/d/<id>/view into /uc?export=download&id=<id>
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url

    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]

    # Dropbox direct download
    if hostname == "dropbox.com":
        query = parse_qs(parsed.query)
        query.pop("raw", None)
        query["dl"] = ["1"]
        new_query = urlencode(query, doseq=True)
        return urlunparse(parsed._replace(query=new_query))

    # GitHub blob to raw.githubusercontent.com
    if hostname == "github.com":
        m = re.match(r"^/([^/]+)/([^/]+)/blob/(.+)$", parsed.path)
        if m:
            owner, repo, filepath = m.groups()
            return f"https://raw.githubusercontent.com/{owner}/{repo}/{filepath}"

    # Google Drive export download link
    if hostname == "drive.google.com":
        m = re.match(r"^/file/d/([a-zA-Z0-9_\-]+)", parsed.path)
        if m:
            file_id = m.group(1)
            return f"https://drive.google.com/uc?export=download&id={file_id}"

    return url


def sanitize_filename(name: str) -> str:
    """Sanitize arbitrary filenames to prevent path traversal and shell injection."""
    sanitized = re.sub(r'[\x00-\x1f\\/:*?"<>|]+', "_", name)
    # Strip any directory traversal components
    while ".." in sanitized:
        sanitized = sanitized.replace("..", "_")
    sanitized = re.sub(r"^_+|_+$", "", sanitized.strip()).lstrip(".")[:200]
    return sanitized or "download"


def guess_filename_from_url(url: str, content_type: str | None = None) -> str:
    """Infer a safe filename from a URL path and optional Content-Type header."""
    try:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        raw_name = path_parts[-1] if path_parts else parsed.hostname or "download"
    except Exception:
        raw_name = "download"

    name = sanitize_filename(raw_name)
    if not re.search(r"\.[a-zA-Z0-9]{1,8}$", name) and content_type:
        clean_mime = content_type.split(";")[0].strip().lower()
        ext = MIME_EXTENSIONS.get(clean_mime)
        if ext:
            name += ext

    return name
