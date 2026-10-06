import dns from "node:dns/promises";
import fs from "node:fs";
import http from "node:http";
import https from "node:https";
import net from "node:net";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import {
  authenticateRelay,
  jsonError,
  readRelayRequest,
  relaySourceResponse,
  validateRelayTarget,
} from "../common.mjs";

const MAX_REDIRECTS = 8;
const SOURCE_HEADER_TIMEOUT_MS = 30_000;
const SOURCE_IDLE_TIMEOUT_MS = 120_000;

function isPrivateIPv4(ip) {
  if (!net.isIPv4(ip)) return true;
  const [a, b, c] = ip.split(".").map(Number);
  return (
    a === 0 || a === 10 || a === 127 ||
    (a === 100 && b >= 64 && b <= 127) ||
    (a === 169 && b === 254) ||
    (a === 172 && b >= 16 && b <= 31) ||
    (a === 192 && (b === 168 || (b === 0 && (c === 0 || c === 2)) || (b === 88 && c === 99))) ||
    (a === 198 && ((b === 18 || b === 19) || (b === 51 && c === 100))) ||
    (a === 203 && b === 0 && c === 113) ||
    a >= 224
  );
}

function ipv6Groups(ip) {
  let address = ip.toLowerCase();
  if (address.includes(".")) {
    const lastColon = address.lastIndexOf(":");
    const ipv4 = address.slice(lastColon + 1);
    if (!net.isIPv4(ipv4)) return null;
    const [a, b, c, d] = ipv4.split(".").map(Number);
    address = `${address.slice(0, lastColon + 1)}${((a << 8) | b).toString(16)}:${((c << 8) | d).toString(16)}`;
  }
  const compressedAt = address.indexOf("::");
  if (compressedAt !== address.lastIndexOf("::")) return null;
  const left = (compressedAt < 0 ? address : address.slice(0, compressedAt)).split(":").filter(Boolean);
  const right = compressedAt < 0 ? [] : address.slice(compressedAt + 2).split(":").filter(Boolean);
  const zeroCount = compressedAt < 0 ? 0 : 8 - left.length - right.length;
  if ((compressedAt < 0 && left.length !== 8) || (compressedAt >= 0 && zeroCount < 1)) return null;
  const parts = [...left, ...Array.from({ length: zeroCount }, () => "0"), ...right];
  if (parts.length !== 8 || parts.some((part) => !/^[\da-f]{1,4}$/.test(part))) return null;
  return parts.map((part) => Number.parseInt(part, 16));
}

function isPrivateIp(ip) {
  if (net.isIPv4(ip)) return isPrivateIPv4(ip);
  if (!net.isIPv6(ip)) return true;
  const groups = ipv6Groups(ip);
  if (!groups || (groups[0] & 0xe000) !== 0x2000) return true;
  if (groups[0] === 0x2001 && (groups[1] & 0xfe00) === 0) return true;
  if (groups[0] === 0x2001 && groups[1] === 0x0db8) return true;
  if (groups[0] === 0x2001 && groups[1] === 0x0002 && groups[2] === 0x0000) return true;
  if (groups[0] === 0x2001 && groups[1] === 0x0010 && (groups[2] & 0xfff0) === 0) return true;
  if (groups[0] === 0x2001 && groups[1] === 0x0020 && (groups[2] & 0xfff0) === 0) return true;
  if (groups[0] === 0x5f00) return true;
  if (groups[0] === 0x3fff && (groups[1] & 0xf000) === 0) return true;
  if (groups[0] === 0x2002) return true;
  return false;
}

async function resolvePublicAddresses(url) {
  validateRelayTarget(url.toString());
  const host = url.hostname.replace(/^\[|\]$/g, "");
  const addresses = net.isIP(host)
    ? [{ address: host, family: net.isIPv4(host) ? 4 : 6 }]
    : await dns.lookup(host, { all: true, verbatim: true }).catch(() => []);
  if (!addresses.length) throw new Error("could not resolve source host");
  if (addresses.some(({ address }) => isPrivateIp(address))) {
    throw new Error("private, non-public, or special-use source addresses are not allowed");
  }
  return addresses;
}

function responseHeaders(message) {
  const headers = new Headers();
  for (let index = 0; index < message.rawHeaders.length; index += 2) {
    const name = message.rawHeaders[index];
    const value = message.rawHeaders[index + 1];
    if (name && value !== undefined) headers.append(name, value);
  }
  return headers;
}

async function requestSource(url, method, sourceHeaders, addresses, signal) {
  const expectedHost = url.hostname.toLowerCase().replace(/\.$/, "").replace(/^\[|\]$/g, "");
  const requestFn = url.protocol === "https:" ? https.request : http.request;

  return new Promise((resolve, reject) => {
    let settled = false;
    const request = requestFn(url, {
      method,
      headers: sourceHeaders,
      lookup(hostname, options, callback) {
        if (hostname.toLowerCase().replace(/\.$/, "") !== expectedHost) {
          callback(Object.assign(new Error("connection hostname was not validated"), { code: "ENOTFOUND" }));
          return;
        }
        const candidates = addresses.filter((entry) => !options.family || options.family === entry.family);
        if (!candidates.length) {
          callback(Object.assign(new Error("no validated address for requested IP family"), { code: "ENOTFOUND" }));
          return;
        }
        if (options.all) callback(null, candidates);
        else callback(null, candidates[0].address, candidates[0].family);
      },
    });

    const abort = () => request.destroy(signal.reason instanceof Error ? signal.reason : new Error("cancelled"));
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });

    request.setTimeout(SOURCE_HEADER_TIMEOUT_MS, () => request.destroy(new Error("source response headers timed out")));
    request.once("error", (error) => {
      signal.removeEventListener("abort", abort);
      if (!settled) reject(error);
    });
    request.once("response", (message) => {
      settled = true;
      signal.removeEventListener("abort", abort);
      message.setTimeout(SOURCE_IDLE_TIMEOUT_MS, () => message.destroy(new Error("source stopped sending data")));
      const status = message.statusCode ?? 502;
      const bodyForbidden = method === "HEAD" || status === 204 || status === 205 || status === 304;
      if (bodyForbidden) message.resume();
      const body = bodyForbidden ? null : Readable.toWeb(message);
      resolve(new Response(body, {
        status,
        statusText: message.statusMessage ?? "",
        headers: responseHeaders(message),
      }));
    });
    request.end();
  });
}

async function fetchSource(url, method, sourceHeaders, signal) {
  let current = url;
  const firstOrigin = current.origin;

  for (let redirect = 0; redirect < MAX_REDIRECTS; redirect++) {
    const addresses = await resolvePublicAddresses(current);
    const response = await requestSource(
      current,
      method,
      {
        Accept: "*/*",
        "Accept-Encoding": "identity",
        ...(current.origin === firstOrigin ? sourceHeaders : {}),
      },
      addresses,
      signal,
    ).catch(() => {
      throw new Error("could not reach the source server");
    });

    const location = response.headers.get("location");
    if (response.status >= 300 && response.status < 400 && location) {
      await response.body?.cancel().catch(() => {});
      current = new URL(location, current);
      continue;
    }
    return { response, finalUrl: current };
  }
  throw new Error("too many redirects");
}

function configuredSecret() {
  const file = process.env.RELAY_SHARED_SECRET_FILE?.trim();
  const secret = file ? fs.readFileSync(file, "utf8").trim() : process.env.RELAY_SHARED_SECRET?.trim();
  if (!secret || secret.length < 32) throw new Error("RELAY_SHARED_SECRET must be at least 32 characters");
  return secret;
}

async function handleRelay(request, secret) {
  const url = new URL(request.url);
  if (request.method === "GET" && url.pathname === "/relay") {
    return Response.json(
      { ok: true, relay: "github-self-hosted-worker" },
      { headers: { "Cache-Control": "no-store" } },
    );
  }
  if (request.method !== "POST" || url.pathname !== "/relay") return jsonError("not found", 404);
  if (!(await authenticateRelay(request, secret))) return jsonError("unauthorized", 401);

  let relayRequest;
  try {
    relayRequest = await readRelayRequest(request);
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "invalid relay request", 400);
  }

  try {
    const { response, finalUrl } = await fetchSource(
      relayRequest.url,
      relayRequest.method,
      relayRequest.headers,
      request.signal,
    );
    return relaySourceResponse(response, finalUrl, "github-self-hosted-worker");
  } catch (error) {
    return jsonError(error instanceof Error ? error.message : "relay request failed", 502);
  }
}

function requestHeaders(request) {
  const headers = new Headers();
  for (const [name, raw] of Object.entries(request.headers)) {
    if (Array.isArray(raw)) raw.forEach((value) => headers.append(name, value));
    else if (raw !== undefined) headers.append(name, raw);
  }
  return headers;
}

async function serveNodeRequest(nodeRequest, nodeResponse, secret) {
  const controller = new AbortController();
  const abort = () => controller.abort(new Error("client disconnected"));
  nodeRequest.once("aborted", abort);
  nodeResponse.once("close", () => {
    if (!nodeResponse.writableEnded) abort();
  });

  try {
    const headers = requestHeaders(nodeRequest);
    const host = headers.get("host") ?? "127.0.0.1";
    const method = nodeRequest.method ?? "GET";
    const body = method === "GET" || method === "HEAD" ? undefined : Readable.toWeb(nodeRequest);
    const request = new Request(`http://${host}${nodeRequest.url ?? "/"}`, {
      method,
      headers,
      body,
      ...(body ? { duplex: "half" } : {}),
      signal: controller.signal,
    });
    const response = await handleRelay(request, secret);
    nodeResponse.statusCode = response.status;
    nodeResponse.statusMessage = response.statusText;
    response.headers.forEach((value, name) => nodeResponse.setHeader(name, value));
    if (!response.body || method === "HEAD") {
      nodeResponse.end();
      return;
    }
    await pipeline(Readable.fromWeb(response.body), nodeResponse);
  } catch (error) {
    if (!nodeResponse.headersSent) {
      nodeResponse.statusCode = 500;
      nodeResponse.setHeader("Cache-Control", "no-store");
      nodeResponse.setHeader("Content-Type", "application/json");
      nodeResponse.end(JSON.stringify({ error: "relay worker failed" }));
    } else {
      nodeResponse.destroy(error instanceof Error ? error : undefined);
    }
  } finally {
    nodeRequest.removeListener("aborted", abort);
  }
}

const port = Number(process.env.PORT ?? "8789");
if (!Number.isSafeInteger(port) || port < 1 || port > 65535) throw new Error("PORT must be a valid TCP port");
const host = process.env.HOST ?? "0.0.0.0";
const secret = configuredSecret();
const server = http.createServer((request, response) => {
  void serveNodeRequest(request, response, secret);
});
server.maxHeadersCount = 64;
server.headersTimeout = 10_000;
server.requestTimeout = 20_000;
server.keepAliveTimeout = 5_000;
server.listen(port, host, () => {
  console.log(`GitHub self-hosted relay listening on ${host}:${port}`);
});

function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10_000).unref();
}
process.once("SIGTERM", shutdown);
process.once("SIGINT", shutdown);
