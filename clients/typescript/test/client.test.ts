import { afterEach, describe, expect, it, vi } from "vitest";
import { GateClient, GateError, type Decision } from "../src/index";

const DECISION: Decision = {
  id: "dec_abc",
  action: "route",
  primary: "opt_out",
  flags: [
    {
      category: "opt_out",
      rule_id: "opt-out",
      queue: "compliance",
      priority: "high",
      confidence: 0.97,
      level: "confident",
    },
  ],
  error: null,
  policy: { name: "legal-triggers", version: "0.1.0" },
  backend: { name: "typesafe-jev", model: "jev-1.13.0" },
  conversation_id: "c_1",
  latency_ms: 120,
};

interface Call {
  url: string;
  init: RequestInit;
}

function fakeFetch(responses: Array<Response | Error | "hang">): {
  fetch: typeof fetch;
  calls: Call[];
} {
  const calls: Call[] = [];
  const queue = [...responses];
  const fn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} });
    const next = queue.shift() ?? new Error("no more responses");
    if (next === "hang") {
      return new Promise<Response>((_, reject) => {
        init?.signal?.addEventListener("abort", () =>
          reject(new DOMException("aborted", "AbortError")),
        );
      });
    }
    if (next instanceof Error) throw next;
    return next;
  }) as typeof fetch;
  return { fetch: fn, calls };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });

describe("GateClient", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("posts to /v1/gate with auth and snake_case body", async () => {
    const { fetch, calls } = fakeFetch([json(DECISION)]);
    const gate = new GateClient({ baseUrl: "http://gate:8080/", apiKey: "k", fetch });
    const d = await gate.check("pls stop texting me", {
      conversationId: "c_1",
      channel: "sms",
      recentMessages: ["earlier"],
    });
    expect(d).toEqual(DECISION);
    expect(calls).toHaveLength(1);
    const call = calls[0]!;
    expect(call.url).toBe("http://gate:8080/v1/gate");
    expect(call.init.method).toBe("POST");
    const headers = new Headers(call.init.headers);
    expect(headers.get("authorization")).toBe("Bearer k");
    expect(headers.get("content-type")).toBe("application/json");
    expect(JSON.parse(String(call.init.body))).toEqual({
      message: "pls stop texting me",
      conversation_id: "c_1",
      channel: "sms",
      recent_messages: ["earlier"],
    });
  });

  it("omits optional fields that were not given", async () => {
    const { fetch, calls } = fakeFetch([json(DECISION)]);
    await new GateClient({ baseUrl: "http://gate", fetch }).check("hi");
    expect(JSON.parse(String(calls[0]!.init.body))).toEqual({ message: "hi" });
    expect(new Headers(calls[0]!.init.headers).has("authorization")).toBe(false);
  });

  it("targets a named pack", async () => {
    const { fetch, calls } = fakeFetch([json(DECISION)]);
    await new GateClient({ baseUrl: "http://gate", pack: "outbound-claims", fetch }).check("x");
    expect(calls[0]!.url).toBe("http://gate/v1/packs/outbound-claims/gate");
  });

  it("encodes the pack name in the path", async () => {
    const { fetch, calls } = fakeFetch([json(DECISION)]);
    await new GateClient({ baseUrl: "http://gate", pack: "a/b c", fetch }).check("x");
    expect(calls[0]!.url).toBe("http://gate/v1/packs/a%2Fb%20c/gate");
  });

  it("returns a review decision when the sidecar is unreachable", async () => {
    const { fetch } = fakeFetch([new TypeError("fetch failed")]);
    const d = await new GateClient({ baseUrl: "http://gate", fetch }).check("hi", {
      conversationId: "c_9",
    });
    expect(d.action).toBe("review");
    expect(d.error?.code).toBe("gate_unreachable");
    expect(d.flags).toEqual([]);
    expect(d.primary).toBeNull();
    expect(d.conversation_id).toBe("c_9");
    expect(d.id).toMatch(/^dec_client_[0-9a-f]{32}$/);
    expect(d.backend).toEqual({ name: "none", model: null });
  });

  it("times out into gate_unreachable", async () => {
    const { fetch } = fakeFetch(["hang"]);
    const started = Date.now();
    const d = await new GateClient({ baseUrl: "http://gate", timeoutMs: 20, fetch }).check("hi");
    expect(d.error?.code).toBe("gate_unreachable");
    expect(d.error?.message).toMatch(/timed out/);
    expect(Date.now() - started).toBeLessThan(1000);
  });

  it("treats 5xx as unreachable", async () => {
    const { fetch } = fakeFetch([json({ detail: "boom" }, 503)]);
    const d = await new GateClient({ baseUrl: "http://gate", fetch }).check("hi");
    expect(d.error?.code).toBe("gate_unreachable");
  });

  it("treats 4xx as rejected", async () => {
    const { fetch } = fakeFetch([json({ detail: "invalid or missing API key" }, 401)]);
    const d = await new GateClient({ baseUrl: "http://gate", fetch }).check("hi");
    expect(d.action).toBe("review");
    expect(d.error?.code).toBe("gate_rejected");
    expect(d.error?.message).toContain("401");
  });

  it("treats a non-JSON 200 as unreachable", async () => {
    const { fetch } = fakeFetch([new Response("<html>", { status: 200 })]);
    const d = await new GateClient({ baseUrl: "http://gate", fetch }).check("hi");
    expect(d.error?.code).toBe("gate_unreachable");
  });

  it("treats a JSON 200 that is not a decision as unreachable", async () => {
    for (const body of [{ status: "ok" }, { action: "maybe", flags: [] }, { action: "route" }]) {
      const { fetch } = fakeFetch([json(body)]);
      const d = await new GateClient({ baseUrl: "http://gate", fetch }).check("hi");
      expect(d.action).toBe("review");
      expect(d.error?.code).toBe("gate_unreachable");
    }
  });

  it("throws GateError when throwOnError is set", async () => {
    const { fetch } = fakeFetch([json({ detail: "nope" }, 422)]);
    const gate = new GateClient({ baseUrl: "http://gate", throwOnError: true, fetch });
    await expect(gate.check("hi")).rejects.toMatchObject({
      name: "GateError",
      code: "gate_rejected",
      status: 422,
    });
    const { fetch: down } = fakeFetch([new TypeError("fetch failed")]);
    const err = await new GateClient({ baseUrl: "http://gate", throwOnError: true, fetch: down })
      .check("hi")
      .catch((e: unknown) => e);
    expect(err).toBeInstanceOf(GateError);
    expect((err as GateError).code).toBe("gate_unreachable");
  });

  it("retries network errors when asked", async () => {
    const { fetch, calls } = fakeFetch([new TypeError("fetch failed"), json(DECISION)]);
    const d = await new GateClient({ baseUrl: "http://gate", retries: 1, fetch }).check("hi");
    expect(d.action).toBe("route");
    expect(calls).toHaveLength(2);
  });

  it("does not retry 4xx", async () => {
    const { fetch, calls } = fakeFetch([json({}, 400), json(DECISION)]);
    const d = await new GateClient({ baseUrl: "http://gate", retries: 3, fetch }).check("hi");
    expect(d.error?.code).toBe("gate_rejected");
    expect(calls).toHaveLength(1);
  });

  it("does not retry by default", async () => {
    const { fetch, calls } = fakeFetch([new TypeError("x"), json(DECISION)]);
    await new GateClient({ baseUrl: "http://gate", fetch }).check("hi");
    expect(calls).toHaveLength(1);
  });

  it("respects a caller abort signal", async () => {
    const { fetch } = fakeFetch(["hang"]);
    const controller = new AbortController();
    const pending = new GateClient({ baseUrl: "http://gate", timeoutMs: 5000, fetch }).check("hi", {
      signal: controller.signal,
    });
    controller.abort();
    const d = await pending;
    expect(d.error?.code).toBe("gate_unreachable");
  });

  it("rejects empty and non-string messages", async () => {
    const { fetch } = fakeFetch([]);
    const gate = new GateClient({ baseUrl: "http://gate", fetch });
    await expect(gate.check("")).rejects.toBeInstanceOf(TypeError);
    await expect(gate.check(42 as unknown as string)).rejects.toBeInstanceOf(TypeError);
  });

  it("falls back safely without Web Crypto (Node 18)", async () => {
    vi.stubGlobal("crypto", undefined);
    const { fetch } = fakeFetch([new TypeError("fetch failed")]);
    const d = await new GateClient({ baseUrl: "http://gate", fetch }).check("hi");
    expect(d.error?.code).toBe("gate_unreachable");
    expect(d.id).toMatch(/^dec_client_[0-9a-f]{32}$/);
  });

  it("requires a baseUrl", () => {
    expect(() => new GateClient({ baseUrl: "" })).toThrow(TypeError);
  });
});
