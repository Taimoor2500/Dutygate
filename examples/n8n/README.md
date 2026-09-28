# DutyGate from n8n, Zapier, Make, or any webhook tool

No-code tools call the DutyGate sidecar with a plain HTTP request. No code or SDK is needed.

## 1. Run the sidecar

```console
docker run -p 8080:8080 \
  -e DUTYGATE_SIDECAR_KEYS=change-me \
  -e TYPESAFE_API_KEY=... \
  ghcr.io/taimoor2500/dutygate
```

## 2. Add an HTTP Request step before the bot's reply

| setting | value |
|---|---|
| Method | `POST` |
| URL | `http://<sidecar-host>:8080/v1/gate` |
| Header | `Authorization: Bearer change-me` |
| Body (JSON) | `{"message": "{{ inbound message text }}", "conversation_id": "{{ conversation id }}", "channel": "sms"}` |
| Timeout | 5 seconds |

The response is the decision object:

```json
{"action": "route", "primary": "opt_out",
 "flags": [{"category": "opt_out", "queue": "compliance", "priority": "high",
            "confidence": 0.97, "level": "confident", "rule_id": "opt-out"}],
 "error": null, "policy": {"name": "legal-triggers", "version": "0.1.0"}, "...": "..."}
```

## 3. Branch on `action`

In n8n, use a **Switch** node on `{{ $json.action }}`:

- `continue`: go on to the bot or LLM step as usual.
- `route`: create a ticket in the queue named by `{{ $json.flags[0].queue }}`, and send a
  neutral holding reply such as *"Thanks for your message. A member of our team will review it
  and follow up with you."* Do not let the bot reply to the flagged part.
- `review`: create a low-priority review task, then continue to the bot. If `{{ $json.error }}`
  is not empty, the gate could not judge the message, so add it to a re-scan queue.

If the HTTP step itself fails (the sidecar is down), treat that as `review`: let the bot reply,
and put the message in a queue to be scanned again later. Never drop it.
