import type { CheckOptions, Decision, GateClientOptions } from "./types";

export type GateErrorCode = "gate_unreachable" | "gate_rejected";

export class GateError extends Error {
  override readonly name = "GateError";
  readonly code: GateErrorCode;
  readonly status: number | undefined;

  constructor(code: GateErrorCode, message: string, status?: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

class Retryable extends Error {}

const ACTIONS = new Set(["continue", "route", "review"]);

function isDecision(value: unknown): value is Decision {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.action === "string" && ACTIONS.has(v.action) && Array.isArray(v.flags);
}

function randomHex(bytes: number): string {
  const buf = new Uint8Array(bytes);
  // Node 18 has no global Web Crypto. This id is only a correlation id, so Math.random is fine.
  const webCrypto = (globalThis as { crypto?: Crypto }).crypto;
  if (webCrypto?.getRandomValues) {
    webCrypto.getRandomValues(buf);
  } else {
    for (let i = 0; i < buf.length; i++) buf[i] = Math.floor(Math.random() * 256);
  }
  return Array.from(buf, (b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * Calls the DutyGate sidecar before a bot replies.
 *
 * By default `check` never throws for gate failures: it returns a `review` decision with
 * `error.code` set to `gate_unreachable` or `gate_rejected`, so the host has one code path
 * (let the bot reply, enqueue a human review, and re-scan the message later).
 */
export class GateClient {
  private readonly url: string;
  private readonly apiKey: string | undefined;
  private readonly timeoutMs: number;
  private readonly retries: number;
  private readonly throwOnError: boolean;
  private readonly pack: string | undefined;
  private readonly fetchImpl: typeof fetch;

  constructor(options: GateClientOptions) {
    if (!options.baseUrl) throw new TypeError("GateClient: baseUrl is required");
    const base = options.baseUrl.replace(/\/+$/, "");
    this.pack = options.pack;
    this.url = options.pack
      ? `${base}/v1/packs/${encodeURIComponent(options.pack)}/gate`
      : `${base}/v1/gate`;
    this.apiKey = options.apiKey;
    this.timeoutMs = options.timeoutMs ?? 3000;
    this.retries = Math.max(0, options.retries ?? 0);
    this.throwOnError = options.throwOnError ?? false;
    this.fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis);
  }

  async check(message: string, options: CheckOptions = {}): Promise<Decision> {
    if (typeof message !== "string" || message.length === 0) {
      throw new TypeError("GateClient.check: message must be a non-empty string");
    }
    const started = Date.now();
    const body: Record<string, unknown> = { message };
    if (options.conversationId !== undefined) body.conversation_id = options.conversationId;
    if (options.channel !== undefined) body.channel = options.channel;
    if (options.recentMessages !== undefined) body.recent_messages = options.recentMessages;

    const headers: Record<string, string> = { "content-type": "application/json" };
    if (this.apiKey) headers.authorization = `Bearer ${this.apiKey}`;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const onAbort = () => controller.abort();
    options.signal?.addEventListener("abort", onAbort, { once: true });
    if (options.signal?.aborted) controller.abort();

    let lastError = "unknown error";
    try {
      for (let attempt = 0; attempt <= this.retries; attempt++) {
        try {
          return await this.once(JSON.stringify(body), headers, controller.signal);
        } catch (err) {
          if (err instanceof GateError) throw err;
          if (controller.signal.aborted) {
            lastError = options.signal?.aborted
              ? "request aborted by caller"
              : `request timed out after ${this.timeoutMs} ms`;
            break;
          }
          lastError = err instanceof Error ? err.message : String(err);
        }
      }
      throw new GateError("gate_unreachable", `DutyGate sidecar unreachable: ${lastError}`);
    } catch (err) {
      const gateError =
        err instanceof GateError
          ? err
          : new GateError("gate_unreachable", `DutyGate sidecar unreachable: ${String(err)}`);
      if (this.throwOnError) throw gateError;
      return this.fallback(gateError, options.conversationId, Date.now() - started);
    } finally {
      clearTimeout(timer);
      options.signal?.removeEventListener("abort", onAbort);
    }
  }

  private async once(
    body: string,
    headers: Record<string, string>,
    signal: AbortSignal,
  ): Promise<Decision> {
    const res = await this.fetchImpl(this.url, { method: "POST", headers, body, signal });
    if (res.status >= 500) {
      throw new Retryable(`HTTP ${res.status}`);
    }
    if (res.status >= 400) {
      const detail = await res.text().catch(() => "");
      throw new GateError(
        "gate_rejected",
        `DutyGate sidecar rejected the request (HTTP ${res.status})${detail ? `: ${detail.slice(0, 200)}` : ""}`,
        res.status,
      );
    }
    let parsed: unknown;
    try {
      parsed = await res.json();
    } catch {
      throw new Retryable("response was not JSON");
    }
    if (!isDecision(parsed)) {
      // A proxy or wrong URL answering 200 must not look like a decision: fail safe.
      throw new Retryable("response was not a DutyGate decision");
    }
    return parsed;
  }

  private fallback(error: GateError, conversationId: string | undefined, latency: number): Decision {
    return {
      id: `dec_client_${randomHex(16)}`,
      action: "review",
      primary: null,
      flags: [],
      error: { code: error.code, message: error.message },
      policy: { name: this.pack ?? "unknown", version: "unknown" },
      backend: { name: "none", model: null },
      conversation_id: conversationId ?? null,
      latency_ms: latency,
    };
  }
}
