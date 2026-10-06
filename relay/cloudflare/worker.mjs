import {
  authenticateRelay,
  jsonError,
  readRelayRequest,
  relaySourceResponse,
  validateRelayTarget,
} from "../common.mjs";

const MAX_REDIRECTS = 8;

async function fetchSource(url, method, sourceHeaders, signal) {
  let current = url;
  const firstOrigin = current.origin;

  for (let redirect = 0; redirect < MAX_REDIRECTS; redirect++) {
    validateRelayTarget(current.toString(), { edge: true });
    let response;
    try {
      response = await fetch(current, {
        method,
        redirect: "manual",
        signal,
        headers: {
          Accept: "*/*",
          "Accept-Encoding": "identity",
          ...(current.origin === firstOrigin ? sourceHeaders : {}),
        },
      });
    } catch {
      throw new Error("could not reach the source server");
    }

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

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/relay") {
      return Response.json(
        { ok: true, relay: "cloudflare-worker" },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
    if (request.method !== "POST" || url.pathname !== "/relay") return jsonError("not found", 404);

    if (typeof env.RELAY_SHARED_SECRET !== "string" || env.RELAY_SHARED_SECRET.length < 32) {
      return jsonError("relay is not configured", 503);
    }
    if (!(await authenticateRelay(request, env.RELAY_SHARED_SECRET))) return jsonError("unauthorized", 401);

    let relayRequest;
    try {
      relayRequest = await readRelayRequest(request, { edge: true });
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
      return relaySourceResponse(response, finalUrl, "cloudflare-worker");
    } catch (error) {
      return jsonError(error instanceof Error ? error.message : "relay request failed", 502);
    }
  },
};
