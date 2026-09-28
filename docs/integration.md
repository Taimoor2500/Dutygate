# Integrating DutyGate

The host (your chatbot or messaging pipeline) needs to do three things:

1. Call the gate with the inbound message **before** generating a reply.
2. Branch on `decision.action`.
3. Send `route` and `review` cases to a queue you already own.

DutyGate never takes the action itself. It never unsubscribes, deletes, refunds or replies.

## The branches

| action | do |
|---|---|
| `continue` | Let the bot reply normally. |
| `route` | Create a case for each flag in its `queue` with its `priority`. Send a neutral **holding reply**. Do not let the bot improvise about the flagged content. |
| `review` | Create a low-priority human review task. The bot may reply, or you can hold (`hold_on_review=True`). Never auto-close the conversation. If `decision.error` is set, the gate could not judge the message, so also queue it for a **re-scan** later. |

`decision.flags` lists every raised rule, confident ones first, then grey ones, each group in
the pack's rule order. A message can carry several obligations ("erase my data and stop the
emails"), and each flag names its own queue.

## Holding replies

The gate reports *what happened*; you decide *what to say*. `default_holding_reply()` returns:

> Thanks for your message. A member of our team will review it and follow up with you.

When you write your own holding replies:
- Acknowledge receipt and say a person will follow up.
- Do **not** admit fault, deny liability, promise an outcome, or state a legal deadline unless
  counsel has approved that wording.
- Do **not** claim an action is complete ("you've been unsubscribed") unless your workflow has
  actually completed it.
- Localize the reply into the customer's language.

If the message also contained an ordinary question, you may answer that part separately. The
v1 adapters don't do this; they send the holding reply only.

## Failure behavior

| situation | what you get | do |
|---|---|---|
| TypeSafe error, timeout, malformed answers | `review` + `error.code` (for example `backend_timeout`) | bot replies, queue a review, re-scan later |
| message over `max_message_chars` | `review` + `message_too_long` | same; consider raising the limit |
| sidecar unreachable (TS client) | `review` + `gate_unreachable` | same |
| sidecar rejects the call (bad key) | `review` + `gate_rejected` | **alert**: this is a configuration bug |
| your `on_route` callback fails (`GatedHandler`) | the exception propagates | let your webhook platform retry, so nothing is silently lost |

To fail *closed* (hold every reply while the gate is down), set `defaults.on_error: route` in
the pack. That turns a vendor outage into a support outage.

## Latency

One TypeSafe request per message, however many questions the pack asks.

**Sequential** (simplest): the gate runs, then the bot. This adds one round trip, capped by
`DUTYGATE_TIMEOUT_MS`.

**Speculative**: start both at once and discard the bot's reply if the gate routes. This
lowers latency but wastes an LLM call on each flagged message.

```python
import asyncio

decision, draft = await asyncio.gather(gate.check_async(message), bot.reply(message))
if decision.action == "route":
    await create_case(decision.flags, message)
    reply = default_holding_reply(decision)
else:
    if decision.action == "review":
        await create_review_task(decision.flags, message)
    reply = draft
```

Measure end-to-end latency on your own traffic.

## Checking the bot's replies too

The `outbound-claims` pack flags replies that claim an action was completed, admit liability,
make legal statements or promise outcomes. With `GatedHandler`, pass
`outbound_gate=Gate.from_pack("packs/outbound-claims.yaml")`. On `route` the reply is replaced
by the holding reply and `on_route` is called. The customer's message is passed as context.

## Duplicate flags

The gate judges one message at a time. If a customer repeats a request ("stop" three times),
each message is flagged. Dedupe in your case system on `(conversation_id, category)`.

## Multi-turn triggers

"Yes, please do that" only means something alongside the earlier turn. Pass `recent_messages`
and set `context.max_recent_messages` in the pack. It is off by default: measure it with the
eval harness before relying on it.
