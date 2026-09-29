<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Taimoor2500/Dutygate/main/docs/assets/dutygate-logo-dark.svg">
    <img src="https://raw.githubusercontent.com/Taimoor2500/Dutygate/main/docs/assets/dutygate-logo.svg" alt="DutyGate" width="340">
  </picture>
</p>

<p align="center">
  <strong>Catch the legal obligations hiding in ordinary support messages before your chatbot replies.</strong>
</p>

<p align="center">
  <a href="https://pypi.org/project/dutygate/"><img src="https://img.shields.io/pypi/v/dutygate?color=4f46e5&label=pypi" alt="PyPI"></a>
  <a href="https://www.npmjs.com/package/dutygate-client"><img src="https://img.shields.io/npm/v/dutygate-client?color=4f46e5&label=npm" alt="npm"></a>
  <a href="https://pypi.org/project/dutygate/"><img src="https://img.shields.io/pypi/pyversions/dutygate?color=4f46e5" alt="Python versions"></a>
  <a href="https://github.com/Taimoor2500/Dutygate/actions/workflows/ci.yml"><img src="https://github.com/Taimoor2500/Dutygate/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-4f46e5" alt="MIT license"></a>
</p>

![DutyGate demo: legal triggers in customer messages are held before the bot replies](https://raw.githubusercontent.com/Taimoor2500/Dutygate/main/docs/assets/dutygate-demo.gif)

"pls stop texting me" is an opt-out. "I want everything you have on me" is a privacy access
request. "My lawyer will hear about this" is a legal threat. Topic triage files these under
*billing* or *angry customer*, keyword lists miss the way people actually write, and an LLM bot
that answers "Done, you're unsubscribed!" when nothing happened creates the liability itself.

DutyGate is a small, chatbot-agnostic gate placed in front of the reply step. It reads every
inbound message, asks [TypeSafe Jev](https://docs.typesafe.ai) a batch of yes/no questions in
**one** call, applies versioned rules from a YAML **policy pack**, and tells your code what to do:

```
inbound message ──► DUTYGATE ──► continue ──► bot replies normally
                        ├── route  ──► holding reply + case in the right queue
                        └── review ──► bot may reply; a human takes a look
```

- **Flags and routes, never acts.** It does not unsubscribe, delete, refund or reply on its
  own. Your people and workflows do that.
- **Recall-first.** A miss can cost a statutory deadline; a false alarm costs a reviewer a few
  seconds. Low-confidence signals go to `review`, not to `continue`.
- **Fails safe.** If TypeSafe is down, slow, or returns something malformed, you get a `review`
  decision with an error code, never an exception or a dropped message.
- **Auditable.** Rules are versioned YAML, testable offline, with a published evaluation
  harness and a cross-language conformance suite.

> **Not legal advice.** Which categories matter, their deadlines, and how they are routed depend
> on your jurisdiction and business. Have counsel review the packs and your holding replies
> before production use.

## Quickstart

Offline, with no API key. The reference packs, their sample datasets and keyword lists ship
inside the package, so they can be used by name. The `keyword` backend here is the naive
baseline, which exists only for evaluation and demos.

```console
pip install 'dutygate[server]'

dutygate validate legal-triggers outbound-claims
dutygate run legal-triggers --backend keyword --state "pls stop texting me"
dutygate eval legal-triggers --backend keyword
```

With TypeSafe Jev, the real backend:

```console
export TYPESAFE_API_KEY=...        # from typesafe.ai
export DUTYGATE_JEV_MODEL=jev-1.13.0   # pin the model in production
dutygate run legal-triggers --state "I want everything you have on me"
dutygate eval legal-triggers    # scores Jev on the bundled sample dataset
```

## Make it yours

Copy a reference pack, with its sample dataset and keyword list, into your project and edit
it. No code is involved: questions, thresholds, queues and new categories are all YAML.

```console
dutygate init legal-triggers      # writes legal-triggers.yaml, .dataset.jsonl, .keywords.yaml
# edit legal-triggers.yaml (and give it your own `name`), add rows to the dataset
dutygate validate legal-triggers.yaml
dutygate eval legal-triggers.yaml legal-triggers.dataset.jsonl --save-answers answers.jsonl
dutygate eval legal-triggers.yaml legal-triggers.dataset.jsonl --replay answers.jsonl --sweep
```

Then point your bot at your file: `Gate.from_pack("legal-triggers.yaml")`. To measure it on
real traffic, add your own labeled messages to the dataset; see
[docs/labeling.md](docs/labeling.md). The format is in [SPEC.md](SPEC.md).

## Use it from your bot

### Python

```python
from dutygate import Gate, default_holding_reply

gate = Gate.from_pack("packs/legal-triggers.yaml")  # TypeSafe Jev, configured from env

decision = await gate.check_async(message, conversation_id=cid, channel="sms")
if decision.action == "route":
    await create_case(decision.flags, message)  # your ticketing / queue
    reply = default_holding_reply(decision)  # neutral; no bot improvisation
elif decision.action == "review":
    await create_review_task(decision.flags, message)
    if decision.error:  # the gate could not judge it
        await enqueue_rescan(message)
    reply = await bot.reply(message)
else:
    reply = await bot.reply(message)
```

`GatedHandler` (in `dutygate.adapters.webhook`) wraps exactly this logic for any web
framework, `with_legal_gate` does the same for LangChain runnables, and
`gate_node` / `outbound_node` add DutyGate to a LangGraph graph. See
[docs/adapters.md](docs/adapters.md).

### Any language: the HTTP sidecar

```console
DUTYGATE_SIDECAR_KEYS=change-me TYPESAFE_API_KEY=... \
  dutygate serve packs/legal-triggers.yaml packs/outbound-claims.yaml --host 0.0.0.0

curl -H 'Authorization: Bearer change-me' -H 'content-type: application/json' \
  -d '{"message": "pls stop texting me", "channel": "sms"}' localhost:8080/v1/gate
```

Or use the Docker image, the [TypeScript client](clients/typescript) (`dutygate-client`), or
any no-code tool ([n8n / Zapier recipe](examples/n8n/README.md)). See
[docs/sidecar.md](docs/sidecar.md).

## The decision

```json
{
  "id": "dec_4f1c2a9e8b7d4c3fa1e2b3c4d5e6f708",
  "action": "route",
  "primary": "privacy_request",
  "flags": [
    {"category": "privacy_request", "rule_id": "privacy-request", "queue": "privacy",
     "priority": "high", "confidence": 0.93, "level": "confident"},
    {"category": "opt_out", "rule_id": "opt-out", "queue": "compliance",
     "priority": "high", "confidence": 0.31, "level": "grey"}
  ],
  "error": null,
  "policy": {"name": "legal-triggers", "version": "0.2.0"},
  "backend": {"name": "typesafe-jev", "model": "jev-1.13.0"},
  "conversation_id": "c_123",
  "latency_ms": 212
}
```

| `action` | meaning | your bot should |
|---|---|---|
| `continue` | no trigger | reply normally |
| `route` | at least one confident trigger | create a case, send a neutral holding reply, and not improvise about the trigger |
| `review` | a grey-zone signal, or the gate could not judge (`error` is set) | reply if you like, queue a human review, never auto-close; re-scan later if `error` is set |

`primary` is the first confident flag in the pack's rule order (or the first grey one).
Error codes and every field are specified in [SPEC.md](SPEC.md).

## What it detects

| pack | categories |
|---|---|
| `legal-triggers` (inbound) | `legal_threat`, `regulator_complaint`, `privacy_request`, `chargeback_dispute`, `opt_out`, `accessibility_request` |
| `outbound-claims` (the bot's own reply) | `admits_liability`, `claims_action_completed`, `legal_statement`, `promises_outcome` |

One message can raise several flags ("erase my data and stop the emails"). Queues and
priorities are examples: map them to your own systems. Packs are plain YAML, so you can add
categories or tighten questions without touching code ([SPEC.md](SPEC.md)).

## Surfaces

| surface | status |
|---|---|
| Python library (`Gate`, `evaluate`) | ✅ |
| CLI: `validate`, `run`, `eval`, `serve` | ✅ |
| HTTP sidecar + Docker image | ✅ |
| TypeScript client `dutygate-client` | ✅ passes the conformance suite end to end |
| `GatedHandler` for any web framework (FastAPI, Flask examples) | ✅ |
| LangChain `with_legal_gate` | ✅ |
| LangGraph gate and outbound nodes | ✅ |

Every surface must reproduce [`conformance/cases.json`](conformance/cases.json).

## Evaluation

The repo ships synthetic labeled datasets, a deliberately naive keyword baseline, and a
harness that scores any backend, saves raw answers, and sweeps thresholds offline.

On the bundled `legal-triggers` set, the keyword baseline catches **48%** of triggers
(0% of non-English ones) and false-alarms on **13%** of clean messages. The datasets were
written by the same author as the baseline, so they are a sanity check, not a benchmark:
measure on your own traffic before you rely on this. See [evals/README.md](evals/README.md).

**If Jev does not beat a keyword list on your data, do not pay for it.**

## Status

| item | state |
|---|---|
| Packs, engine, validator, CLI, eval harness, sidecar, TS client, adapters | built and tested offline (Python coverage ≥ 90%) |
| Live TypeSafe Jev integration | built against the published API reference and tested with mocked HTTP; **not yet verified against the live API** (`pytest -m live`) |
| Question wording and thresholds | untuned; tune with `dutygate eval --save-answers` then `--replay --sweep` |

## Docs

- [SPEC.md](SPEC.md): pack format, evaluation algorithm, decision contract (normative)
- [docs/integration.md](docs/integration.md): host contract, holding replies, failure behavior, latency patterns
- [docs/sidecar.md](docs/sidecar.md): HTTP API, auth, metrics, audit log, Docker
- [docs/adapters.md](docs/adapters.md): `GatedHandler`, LangChain, LangGraph
- [docs/privacy.md](docs/privacy.md): what leaves your system, redaction, prompt injection
- [docs/labeling.md](docs/labeling.md): building a real evaluation set
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [CHANGELOG.md](CHANGELOG.md)

## License

MIT. See [LICENSE](LICENSE).
