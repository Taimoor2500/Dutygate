/**
 * Runs every case in conformance/cases.json through a real sidecar with the replay backend.
 * Needs uv and the Python package: DUTYGATE_E2E=1 npm test
 */
import { spawn, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import { createServer } from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { GateClient, type Decision } from "../src/index";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const enabled = process.env.DUTYGATE_E2E === "1";

interface Case {
  name: string;
  pack: string;
  input: {
    message: string;
    conversation_id?: string;
    channel?: string;
    recent_messages?: string[];
  };
  expected: Record<string, unknown>;
}

const doc = JSON.parse(readFileSync(resolve(ROOT, "conformance/cases.json"), "utf8")) as {
  packs: Record<string, string>;
  cases: Case[];
};

function normalize(d: Decision): Record<string, unknown> {
  return {
    action: d.action,
    primary: d.primary,
    flags: d.flags,
    error_code: d.error ? d.error.code : null,
    policy: d.policy,
    backend_name: d.backend.name,
    conversation_id: d.conversation_id,
  };
}

function freePort(): Promise<number> {
  return new Promise((ok, fail) => {
    const srv = createServer();
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      srv.close(() => (typeof addr === "object" && addr ? ok(addr.port) : fail(new Error("port"))));
    });
  });
}

describe.skipIf(!enabled)("conformance against a live sidecar", () => {
  let proc: ChildProcess;
  let baseUrl = "";
  let logs = "";

  beforeAll(async () => {
    const port = await freePort();
    baseUrl = `http://127.0.0.1:${port}`;
    const packs = Object.values(doc.packs).map((p) => resolve(ROOT, p));
    proc = spawn(
      "uv",
      ["run", "dutygate", "serve", ...packs, "--backend", "replay", "--fixtures",
        resolve(ROOT, "conformance/cases.json"), "--port", String(port), "--insecure-no-auth",
        "--log-level", "warning"],
      { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] },
    );
    proc.stdout?.on("data", (b: Buffer) => (logs += b.toString()));
    proc.stderr?.on("data", (b: Buffer) => (logs += b.toString()));
    const deadline = Date.now() + 60_000;
    for (;;) {
      try {
        const res = await fetch(`${baseUrl}/readyz`);
        if (res.ok) break;
      } catch {
        /* not up yet */
      }
      if (Date.now() > deadline || proc.exitCode !== null) {
        throw new Error(`sidecar did not start:\n${logs}`);
      }
      await new Promise((r) => setTimeout(r, 200));
    }
  }, 90_000);

  afterAll(() => {
    proc?.kill("SIGTERM");
  });

  it.each(doc.cases.map((c) => [c.name, c] as const))("%s", async (_name, c) => {
    const gate = new GateClient({ baseUrl, pack: c.pack, timeoutMs: 10_000, throwOnError: true });
    const opts: Parameters<GateClient["check"]>[1] = {};
    if (c.input.conversation_id !== undefined) opts.conversationId = c.input.conversation_id;
    if (c.input.channel !== undefined) opts.channel = c.input.channel;
    if (c.input.recent_messages !== undefined) opts.recentMessages = c.input.recent_messages;
    const decision = await gate.check(c.input.message, opts);
    expect(normalize(decision)).toEqual(c.expected);
  });
});
