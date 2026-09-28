# DutyGate specification

Version 1 (pack `schema_version: 1`, HTTP API `/v1`). This document is normative: every
DutyGate surface must behave as described here, and `conformance/cases.json` pins that
behavior with test cases.

The key words MUST, MUST NOT, SHOULD and MAY are used as in RFC 2119.

## 1. Policy packs

A pack is a YAML (or equivalent JSON) mapping. Unknown keys are errors. Loaders accept a
file path or, when no such file exists, the name of a pack bundled with the package
(`legal-triggers`, `outbound-claims`).

### 1.1 Top level

| field | type | required | default | meaning |
|---|---|---|---|---|
| `schema_version` | int | yes | | format version; MUST be `1` |
| `name` | string `^[a-z0-9][a-z0-9-]{0,63}$` | yes | | pack identifier; also the sidecar path segment |
| `version` | semver string | yes | | version of the pack's *content*; bump it when questions, thresholds or routing change |
| `description` | string | no | `""` | |
| `state_field` | string `^[a-z][a-z0-9_]{0,63}$` | no | `customer_message` | key under which the message is placed in backend state; `recent_messages` and `channel` are reserved |
| `defaults` | mapping | no | see 1.2 | |
| `limits` | mapping | no | see 1.3 | |
| `context` | mapping | no | see 1.4 | |
| `redaction` | list | no | `[]` | see 1.5 |
| `questions` | list, at least 1 | yes | | see 1.6 |
| `rules` | list, at least 1 | yes | | see 1.7 |

### 1.2 `defaults`

| field | type | default | meaning |
|---|---|---|---|
| `thresholds` | `{low, high}` | `{low: 0.2, high: 0.5}` | `0 ≤ low ≤ high ≤ 1`. A rule's score `≥ high` is **confident**; `low ≤ score < high` is **grey**; below `low` the rule is not raised |
| `on_error` | `review` \| `route` \| `continue` | `review` | the action returned when the gate cannot judge a message |

### 1.3 `limits`

| field | type | default | meaning |
|---|---|---|---|
| `max_message_chars` | int ≥ 1 | `8000` | messages longer than this (in Unicode code points) are not sent; the `on_error` action is returned with `message_too_long` |

### 1.4 `context`

| field | type | default | meaning |
|---|---|---|---|
| `max_recent_messages` | int 0–50 | `0` | how many of the caller's `recent_messages` (the most recent ones) are included in state; `0` ignores them |

### 1.5 `redaction`

Each entry is `{name, pattern, replacement?, luhn?}`:

- `name`: `^[a-z][a-z0-9_]{0,63}$`, unique within the pack.
- `pattern`: a regular expression (Python `re` syntax). Patterns are trusted configuration and
  SHOULD run in linear time. Anchor repeated character classes with a lookbehind where
  needed; see the reference `email` pattern.
- `replacement`: the text substituted for each match. Default `[NAME]`, the upper-cased name.
  It is used literally (no backreferences).
- `luhn`: when true, a match is redacted only where its digits pass the Luhn checksum (13–19
  digits). Within a match, every run of consecutive whole digit groups is tried, longest
  first, so a card followed or preceded by other digits (a CVV, an expiry) is still redacted,
  while a Luhn-invalid order number is left alone.

Rules are applied in order, to the message and to every included recent message, before
anything is sent to a backend.

### 1.6 `questions`

Each entry is `{id, instructions, criteria?}`:

- `id`: `^[a-z][a-z0-9_]{0,63}$`, unique. It is used as the backend question key.
- `instructions`: a yes/no question about the state. A high score MUST mean "yes".
- `criteria`: optional descriptions of what counts as yes (`true`) and as no (`false`). In
  YAML, bare `true:` / `false:` keys are accepted.

Every question in the pack is sent on every evaluation, even one no rule uses (that case
produces a validation warning).

### 1.7 `rules`

Each entry is `{id, category, match?, questions, queue, priority, thresholds?}`:

| field | meaning |
|---|---|
| `id` | `^[a-z0-9][a-z0-9-]{0,63}$`, unique |
| `category` | `^[a-z][a-z0-9_]{0,63}$`; what the flag is called. Several rules MAY share a category |
| `match` | `any` (default): the rule's score is the **maximum** of its questions' scores. `all`: the **minimum**, so every question must clear the bar |
| `questions` | one or more question ids, no duplicates |
| `queue` | free-form routing hint for the host |
| `priority` | `urgent` \| `high` \| `normal` \| `low`; routing hint for the host |
| `thresholds` | optional `{low, high}` override of `defaults.thresholds` |

**Rule order is precedence.** The first rule is the most important one: it decides `primary`
and the order of `flags`.

### 1.8 Validation

A pack MUST be rejected, with every problem reported together, if any of these apply:
- a schema violation, an unknown key, or an unsupported `schema_version`
- a duplicate question id, rule id or redaction name
- a rule that references an unknown question, lists a question twice, or has no questions
- thresholds violating `0 ≤ low ≤ high ≤ 1`
- a regex that does not compile
- a `version` that is not semver
- no rules
- a reserved `state_field`

Validators SHOULD warn about:
- a question no rule uses
- `on_error: continue` (fails open)
- a rule placed after a rule of lower priority
- `low == high` (no grey zone)
- a redaction pattern that matches the empty string

## 2. Evaluation

Given a pack, a message, and optional `conversation_id`, `channel` and `recent_messages`:

1. **Blank message.** If the message is empty or whitespace, return `continue` with no flags,
   without calling the backend.
2. **Too long.** If `len(message) > limits.max_message_chars`, return the `on_error` action
   with error `message_too_long`, without calling the backend. Messages are never truncated.
3. **Redact** the message and the last `context.max_recent_messages` recent messages.
4. **Build the state object.** Absent parts are omitted:
   `{<state_field>: message, "recent_messages": [...], "channel": channel}`.
5. **Call the backend once**, with all questions.
6. **Validate the answers.** Every question id MUST map to a finite number (not a boolean) in
   `[0, 1]`. Otherwise return the `on_error` action with `malformed_response`. Partial
   answers are never evaluated. Extra keys are ignored.
7. **Score each rule** (max for `any`, min for `all`) and classify it against its thresholds.
   Classification uses the unrounded score; the reported `confidence` is rounded to 4
   decimal places afterwards.
8. **Order the flags**: confident flags first, then grey ones, each group in rule order.
   `primary` is the first flag's category, or `null` if there are none.
9. **Choose the action**: `route` if any flag is confident, else `review` if any is grey, else
   `continue`.

Backend failures map to error codes, and the `on_error` action is returned:

| code | cause |
|---|---|
| `backend_timeout` | no answer within the time budget |
| `backend_unavailable` | connection failure, 5xx, 429 or 529 after retries |
| `backend_auth` | 401 / 403 |
| `backend_rejected` | any other 4xx |
| `malformed_response` | unparseable, incomplete or out-of-range answers |
| `message_too_long` | see step 2 |
| `internal_error` | an unexpected error inside the gate |

The engine MUST NOT raise for any of these. Invalid argument types (a non-string message, for
example) are programming errors and MAY raise.

**Invariant:** raising any single score never lowers the action on the scale
`continue < review < route`.

## 3. Decision

```json
{
  "id": "dec_<32 hex>",
  "action": "continue | route | review",
  "primary": "category or null",
  "flags": [{"category", "rule_id", "queue", "priority", "confidence", "level": "confident | grey"}],
  "error": null | {"code", "message"},
  "policy": {"name", "version"},
  "backend": {"name", "model": "string or null"},
  "conversation_id": "echoed or null",
  "latency_ms": 0
}
```

Keys appear in this order. `id` and `latency_ms` differ on every call and are excluded from
conformance comparisons. Clients MAY add two client-side error codes: `gate_unreachable`
(network error, timeout, 5xx) and `gate_rejected` (4xx). They synthesize a `review` decision
with `backend.name = "none"`.

## 4. TypeSafe Jev mapping

The production backend sends:

```
POST {TYPESAFE_BASE_URL}/v1/systemone
Authorization: Bearer {TYPESAFE_API_KEY}
{"state": <state>, "model": <model>,
 "questions": {<id>: {"type": "noul", "instructions": ..., "criteria": {"true": ..., "false": ...}}}}
```

It reads `answers.<id>.noul`, where `answers.<id>.type` MUST be `"noul"`. The time budget
(`DUTYGATE_TIMEOUT_MS`, default 5000) is a wall-clock limit that covers every attempt,
including reading the response body. Retries (`DUTYGATE_MAX_RETRIES`,
default 1) happen on connection errors, 429, 529 and 5xx, with jittered exponential backoff;
`Retry-After` is honored only if it fits the remaining budget.

## 5. HTTP API (sidecar)

| endpoint | auth | |
|---|---|---|
| `POST /v1/gate` | Bearer | the first pack loaded |
| `POST /v1/packs/{name}/gate` | Bearer | a named pack; 404 if unknown |
| `GET /v1/policy` | Bearer | pack summaries: name, version, description, backend, and each rule's id, category, queue and priority |
| `GET /healthz` | none | liveness |
| `GET /readyz` | none | the loaded packs; never calls the backend |
| `GET /metrics` | none | Prometheus |

Request body (unknown fields are rejected):

| field | type |
|---|---|
| `message` | string, at least 1 character |
| `conversation_id` | string ≤ 256, optional |
| `channel` | string ≤ 64, optional |
| `recent_messages` | list of ≤ 20 strings, optional |

Status codes:
- `200`: the Decision. Backend failures are also `200`, with the `on_error` action and
  `error` set.
- `401`: bad or missing key.
- `413`: body over 1 MB.
- `422`: invalid body. Invalid input values are not echoed back.

Every response carries `X-Request-Id`, echoed from the request when it matches
`[A-Za-z0-9._-]{1,128}`.

## 6. Replay fixtures

JSONL. An optional first line `{"questions_digest": "<sha256>"}` binds the file to a pack's
questions; a mismatch is an error. The digest is the SHA-256 of the canonical JSON of
`[{id, instructions, criteria}]`, sorted by id. Every other line is
`{"message": <raw text>}` plus exactly one of:
- `"scores": {...}`
- `"error": <code>`
- `"raw_answers": {...}`, passed through unvalidated to replay malformed answers

Messages are matched after redaction. `dutygate eval --save-answers` writes this format.

## 7. Conformance

`conformance/cases.json` has the shape
`{"version": 1, "packs": {name: path}, "cases": [...]}`. Each case is
`{name, pack, input: {message, conversation_id?, channel?, recent_messages?}, backend: {scores | error | raw_answers}, expect_state?, expected: {action, primary, flags, error_code, policy, backend_name, conversation_id}}`.

An implementation conforms if, for every case, a replay backend fed the case's `backend`
produces a decision whose reduced form equals `expected`. When `expect_state` is present, the
state sent to the backend MUST equal it.

## 8. Versioning

- The Python package and the npm client share a semver version.
- A pack's `version` is independent of the package version.
- `schema_version` changes only for breaking format changes.
- The HTTP API is versioned by path (`/v1`).
