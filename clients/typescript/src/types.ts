/** What the host should do with the message. */
export type Action = "continue" | "route" | "review";

export type Priority = "urgent" | "high" | "normal" | "low";

/** One detected trigger. `grey` flags are low-confidence signals worth a human look. */
export interface Flag {
  category: string;
  rule_id: string;
  queue: string;
  priority: Priority;
  confidence: number;
  level: "confident" | "grey";
}

export interface ErrorInfo {
  /**
   * Engine codes: backend_timeout, backend_unavailable, backend_auth, backend_rejected,
   * malformed_response, message_too_long, internal_error.
   * Client codes: gate_unreachable (network, timeout, 5xx), gate_rejected (4xx).
   */
  code: string;
  message: string;
}

/** The stable decision contract shared by every DutyGate surface. */
export interface Decision {
  id: string;
  action: Action;
  primary: string | null;
  flags: Flag[];
  error: ErrorInfo | null;
  policy: { name: string; version: string };
  backend: { name: string; model: string | null };
  conversation_id: string | null;
  latency_ms: number;
}

export interface GateClientOptions {
  /** Sidecar base URL, e.g. "http://dutygate:8080". */
  baseUrl: string;
  /** Sidecar API key (one of DUTYGATE_SIDECAR_KEYS). Server-side only: never ship it to a browser. */
  apiKey?: string;
  /** Total time budget per check, including retries. Default 3000. */
  timeoutMs?: number;
  /** Pack to use instead of the sidecar's default pack. */
  pack?: string;
  /** Retries on network errors and 5xx. Default 0: every retry adds reply latency. */
  retries?: number;
  /** Throw GateError instead of returning a synthesized review decision. Default false. */
  throwOnError?: boolean;
  /** Custom fetch implementation (tests, proxies). Defaults to the global fetch. */
  fetch?: typeof fetch;
}

export interface CheckOptions {
  conversationId?: string;
  channel?: string;
  recentMessages?: string[];
  signal?: AbortSignal;
}
