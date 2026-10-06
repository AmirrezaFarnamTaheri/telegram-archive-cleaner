import assert from "node:assert/strict";
import test from "node:test";
import {
  authenticateRelay,
  readRelayRequest,
  relaySourceResponse,
} from "./common.mjs";

test("relay authentication accepts only the configured bearer secret", async () => {
  const secret = "0123456789abcdef0123456789abcdef";
  const valid = new Request("https://relay.example/relay", {
    headers: { Authorization: `Bearer ${secret}` },
  });
  const invalid = new Request("https://relay.example/relay", {
    headers: { Authorization: "Bearer wrong-secret" },
  });
  assert.equal(await authenticateRelay(valid, secret), true);
  assert.equal(await authenticateRelay(invalid, secret), false);
});

test("relay control bodies are capped while streaming when Content-Length is absent", async () => {
  let pulls = 0;
  let cancelled = false;
  const body = new ReadableStream(
    {
      pull(controller) {
        pulls++;
        controller.enqueue(new Uint8Array(8 * 1024).fill(0x20));
        if (pulls >= 8) controller.close();
      },
      cancel() {
        cancelled = true;
      },
    },
    { highWaterMark: 0 },
  );
  const request = new Request("https://relay.example/relay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    duplex: "half",
  });

  await assert.rejects(readRelayRequest(request), /too large/i);
  assert.equal(cancelled, true);
  assert.ok(pulls <= 4, `expected early cancellation, got ${pulls} pulls`);
});

test("relay rejects caller-controlled content encoding", async () => {
  const request = new Request("https://relay.example/relay", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url: "https://example.com/file.bin",
      method: "GET",
      headers: { "Accept-Encoding": "gzip" },
    }),
  });
  await assert.rejects(readRelayRequest(request), /header name not allowed/i);
});

test("relay refuses encoded source bodies instead of silently changing byte semantics", () => {
  const source = new Response(new Uint8Array([1, 2, 3]), {
    headers: {
      "Content-Type": "application/octet-stream",
      "Content-Encoding": "gzip",
    },
  });
  assert.throws(
    () => relaySourceResponse(source, new URL("https://example.com/file.bin"), "test"),
    /unsupported content encoding/i,
  );
});
