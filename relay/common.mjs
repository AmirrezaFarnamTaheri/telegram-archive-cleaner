const MAX_CONTROL_BYTES = 16 * 1024;
const MAX_URL_CHARS = 8192;
const MAX_HEADER_VALUE_CHARS = 4096;
const BLOCKED_HEADERS = new Set(["host", "content-length", "connection", "transfer-encoding", "upgrade", "te", "accept-encoding"]);
const RESERVED_EDGE_HOSTS = new Set([
  "localhost",
  "metadata.google.internal",
  "metadata.google.internal.",
  "instance-data.ec2.internal",
  "instance-data.ec2.internal.",
]);

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function relayHeaders(extra = {}) {
  return {
    "Cache-Control": "no-store, no-transform",
    "X-Content-Type-Options": "nosniff",
    ...extra,
  };
}

export function jsonError(error, status) {
  return Response.json(
    { error },
    { status, headers: relayHeaders({ "X-Link-To-Cloud-Relay-Error": "1" }) },
  );
}

async function digestSecret(value) {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
}

export async function authenticateRelay(request, secret) {
  if (typeof secret !== "string" || secret.length < 32) return false;
  const authorization = request.headers.get("authorization") ?? "";
  if (!authorization.startsWith("Bearer ") || authorization.length > 8192) return false;
  const supplied = authorization.slice("Bearer ".length);
  const [actual, expected] = await Promise.all([digestSecret(supplied), digestSecret(secret)]);
  if (actual.length !== expected.length) return false;
  let difference = 0;
  for (let index = 0; index < actual.length; index++) difference |= actual[index] ^ expected[index];
  return difference === 0;
}

function validateHeaderMap(value) {
  if (value === undefined) return {};
  if (!isRecord(value)) throw new Error("headers must be an object");
  const entries = Object.entries(value);
  if (entries.length > 4) throw new Error("too many source headers");
  const out = {};
  for (const [name, rawValue] of entries) {
    if (!/^[A-Za-z0-9-]+$/.test(name) || BLOCKED_HEADERS.has(name.toLowerCase())) {
      throw new Error("source header name not allowed");
    }
    if (typeof rawValue !== "string" || rawValue.length > MAX_HEADER_VALUE_CHARS || /[\r\n]/.test(rawValue)) {
      throw new Error("invalid source header value");
    }
    out[name] = rawValue;
  }
  return out;
}

export function validateRelayTarget(value, { edge = false } = {}) {
  if (typeof value !== "string" || !value.trim() || value.length > MAX_URL_CHARS) {
    throw new Error("url must be a non-empty string no longer than 8192 characters");
  }
  let url;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error("invalid source URL");
  }
  if ((url.protocol !== "http:" && url.protocol !== "https:") || url.username || url.password) {
    throw new Error("only http(s) URLs without embedded credentials are supported");
  }
  if (edge) {
    const host = url.hostname.toLowerCase().replace(/\.$/, "");
    if (
      RESERVED_EDGE_HOSTS.has(host) ||
      host.endsWith(".localhost") ||
      host.endsWith(".local") ||
      host.endsWith(".internal") ||
      host.endsWith(".home.arpa") ||
      /^\d{1,3}(?:\.\d{1,3}){3}$/.test(host) ||
      host.includes(":")
    ) {
      throw new Error("private, local, or literal-address source hosts are not allowed on the edge relay");
    }
  }
  return url;
}


async function readBoundedBody(request, maxBytes, timeoutMs = 15_000) {
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  let timer;
  const timedOut = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("relay request body timed out")), timeoutMs);
  });

  try {
    for (;;) {
      const { done, value } = await Promise.race([reader.read(), timedOut]);
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => {});
        throw new Error("relay request body is too large");
      }
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel(error).catch(() => {});
    throw error;
  } finally {
    clearTimeout(timer);
    reader.releaseLock();
  }

  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

export async function readRelayRequest(request, { edge = false } = {}) {
  const mediaType = request.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase();
  if (mediaType !== "application/json") throw new Error("Content-Type must be application/json");
  const rawLength = request.headers.get("content-length");
  if (rawLength !== null) {
    if (!/^\d+$/.test(rawLength) || Number(rawLength) > MAX_CONTROL_BYTES) {
      throw new Error("relay request body is too large");
    }
  }
  const bytes = await readBoundedBody(request, MAX_CONTROL_BYTES);
  let body;
  try {
    body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new Error("relay request body must be valid UTF-8 JSON");
  }
  if (!isRecord(body)) throw new Error("relay request body must be a JSON object");
  const allowedKeys = new Set(["url", "method", "headers"]);
  if (Object.keys(body).some((key) => !allowedKeys.has(key))) {
    throw new Error("relay request contains unsupported fields");
  }
  const method = body.method === undefined ? "GET" : body.method;
  if (method !== "GET" && method !== "HEAD") throw new Error("relay method must be GET or HEAD");
  const url = validateRelayTarget(body.url, { edge });
  const headers = validateHeaderMap(body.headers);
  return { url, method, headers };
}

function filteredSourceHeaders(source, finalUrl, platform, maxBytes) {
  const encoding = (source.headers.get("content-encoding") ?? "").toLowerCase();
  if (source.body && encoding && encoding !== "identity") {
    void source.body.cancel().catch(() => {});
    throw new Error("relay source used an unsupported content encoding");
  }
  const headers = new Headers(relayHeaders({
    "X-Link-To-Cloud-Relay": platform,
    "X-Link-To-Cloud-Final-Url": encodeURIComponent(finalUrl.toString()),
  }));
  for (const name of ["content-type", "content-disposition", "etag", "last-modified"]) {
    const value = source.headers.get(name);
    if (value) headers.set(name, value);
  }
  const length = source.headers.get("content-length");
  if ((!encoding || encoding === "identity") && length && /^\d+$/.test(length)) {
    headers.set("content-length", length);
  }
  if (maxBytes !== undefined) headers.set("X-Link-To-Cloud-Max-Bytes", String(maxBytes));
  return headers;
}

export function relaySourceResponse(source, finalUrl, platform, maxBytes) {
  return new Response(source.body, {
    status: source.status,
    statusText: source.statusText,
    headers: filteredSourceHeaders(source, finalUrl, platform, maxBytes),
  });
}
