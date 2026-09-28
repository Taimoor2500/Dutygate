# dutygate-client

TypeScript client for the [DutyGate](https://github.com/Taimoor2500/Dutygate) sidecar. It checks
every inbound customer message for legal and compliance triggers (opt-outs, privacy requests,
legal threats, chargebacks and similar) **before your bot replies**.

- Zero runtime dependencies. Uses the global `fetch` (Node 18+, Bun, Deno, edge runtimes).
- ESM and CommonJS builds, with full types.
- **Server-side only.** The sidecar API key must never reach a browser.

## Install

```console
npm install dutygate-client
```

Run the sidecar next to your bot (see the main README):

```console
docker run -p 8080:8080 -e DUTYGATE_SIDECAR_KEYS=change-me -e TYPESAFE_API_KEY=... \
  ghcr.io/taimoor2500/dutygate
```

## Use

```ts
import { GateClient } from "dutygate-client";

const gate = new GateClient({
  baseUrl: "http://localhost:8080",
  apiKey: process.env.DUTYGATE_KEY,
  timeoutMs: 3000,
});

const decision = await gate.check(message, { conversationId, channel: "sms" });

switch (decision.action) {
  case "continue":
    return bot.reply(message);
  case "route":
    await createCase(decision.flags, message); // your ticketing / queue
    return holdingReply(decision); // neutral acknowledgement; no bot improvisation
  case "review":
    await createReviewTask(decision.flags, message);
    if (decision.error) await enqueueRescan(message); // the gate could not judge it
    return bot.reply(message);
}
```

## Failure behavior

By default `check()` never throws for gate failures. It returns a `review` decision with:

| `error.code` | when |
|---|---|
| `gate_unreachable` | network error, timeout, 5xx, or a response that is not JSON |
| `gate_rejected` | 4xx, such as a bad API key or an invalid request; **alert on this**, it is a configuration bug |

This keeps one code path in your bot: reply normally, queue a human review, and re-scan the
message later so a trigger is caught late rather than lost. Pass `throwOnError: true` to get a
`GateError` (with `code` and `status`) instead.

## Options

| option | default | |
|---|---|---|
| `baseUrl` | (required) | sidecar URL |
| `apiKey` | none | one of the sidecar's `DUTYGATE_SIDECAR_KEYS` |
| `timeoutMs` | `3000` | total budget per check, retries included |
| `pack` | the sidecar's default | calls `/v1/packs/{pack}/gate` |
| `retries` | `0` | retries on network errors and 5xx; each one adds reply latency |
| `throwOnError` | `false` | throw instead of returning a review decision |
| `fetch` | global `fetch` | custom implementation |

`check(message, { conversationId?, channel?, recentMessages?, signal? })`

## Conformance

The client is tested against every case in `conformance/cases.json`, running through a real
sidecar (`npm run test:e2e` from `clients/typescript`, which needs `uv`).

## License

MIT
