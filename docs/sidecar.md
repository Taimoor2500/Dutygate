# HTTP sidecar

`dutygate serve` exposes the gate over HTTP, so any language or no-code tool can use it.

```console
pip install 'dutygate[server]'
export DUTYGATE_SIDECAR_KEYS=key-a,key-b      # comma-separated; more than one for rotation
export TYPESAFE_API_KEY=...
export DUTYGATE_JEV_MODEL=jev-1.13.0          # pin in production
dutygate serve packs/legal-triggers.yaml packs/outbound-claims.yaml --host 0.0.0.0 --port 8080
```

The first pack answers `POST /v1/gate`. Every pack is also available at
`POST /v1/packs/{name}/gate`.

## Docker

```console
docker build -t dutygate .
docker run -p 8080:8080 \
  -e DUTYGATE_SIDECAR_KEYS=change-me -e TYPESAFE_API_KEY=... -e DUTYGATE_JEV_MODEL=jev-1.13.0 \
  dutygate
```

The image runs as a non-root user, bundles `packs/`, and includes a health check. Mount your
own packs and pass them as arguments:

```console
docker run -v "$PWD/my-packs:/my-packs:ro" ... dutygate /my-packs/custom.yaml --host 0.0.0.0
```

## API

```
POST /v1/gate
Authorization: Bearer <key>
Content-Type: application/json

{"message": "pls stop texting me", "conversation_id": "c_123", "channel": "sms",
 "recent_messages": ["..."]}

200 → Decision JSON (see SPEC.md §3)
```

| status | when |
|---|---|
| 200 | a decision; backend failures are also 200, with `action: review` and `error` set |
| 401 | missing or wrong key (`WWW-Authenticate: Bearer`); checked before the body, so it wins over 404, 413 and 422 |
| 404 | unknown pack |
| 413 | body over 1 MB |
| 422 | invalid body; the offending values are not echoed back |

`GET /healthz` (liveness), `GET /readyz` (packs loaded; never calls TypeSafe) and
`GET /metrics` (Prometheus) need no key. `GET /v1/policy` (pack summaries) does.

## Operations

- **Auth is on by default.** Without keys the server refuses to start. `--insecure-no-auth`
  exists for local development and only binds to `127.0.0.1`.
- **Logs** are one JSON object per line on stderr: request id, pack, action, error code and
  latency. Message text is never logged.
- **Audit log**: `--audit-log decisions.jsonl` appends the full decision with a timestamp and
  request id. The path is checked at startup. If a write fails at runtime, the decision is
  still returned and `dutygate_audit_failures_total` is incremented.
  `--audit-include-message` also stores message text; it is off by default, so think about
  retention first.
- **Metrics**:
  - `dutygate_decisions_total{action,pack}`
  - `dutygate_errors_total{code,pack}`
  - `dutygate_decision_seconds{pack}` (a histogram)
  - `dutygate_audit_failures_total`
- **Request ids**: send `X-Request-Id` to correlate calls; otherwise one is generated and
  returned.
- **Offline demos and CI**: `--backend keyword --keywords <file>` or
  `--backend replay --fixtures conformance/cases.json`. Give `--keywords` / `--fixtures` once
  (shared) or once per pack.

## Configuration

| variable | default | |
|---|---|---|
| `DUTYGATE_SIDECAR_KEYS` | (required) | comma-separated API keys |
| `TYPESAFE_API_KEY` | (required for jev) | |
| `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | |
| `DUTYGATE_JEV_MODEL` | `jev-latest` | pin a version in production |
| `DUTYGATE_TIMEOUT_MS` | `5000` | total budget per message, retries included |
| `DUTYGATE_MAX_RETRIES` | `1` | retries on connection errors, 429, 529 and 5xx |

Invalid values stop the server at startup with a message naming the variable.
