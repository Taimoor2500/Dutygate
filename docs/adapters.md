# Adapters

## `GatedHandler`: any web framework or message consumer

```python
from dutygate import Gate
from dutygate.adapters.webhook import GatedHandler

handler = GatedHandler(
    Gate.from_pack("packs/legal-triggers.yaml"),
    reply=bot.reply,  # (message) -> reply
    on_route=create_case,  # (decision, message) -> None
    on_review=create_review_task,  # (decision, message) -> None
    on_gate_failure=enqueue_rescan,  # optional; called when decision.error is set
    holding_reply=my_localized_reply,  # optional; (decision) -> reply
    hold_on_review=False,  # hold the reply on review as well
    outbound_gate=Gate.from_pack("packs/outbound-claims.yaml"),  # optional reply check
)

result = handler.handle(message, conversation_id=cid, channel="sms")  # sync
result = await handler.handle_async(message, conversation_id=cid)  # async
send(result.reply)  # result.decision, result.outbound_decision are there for logging
```

- On `route` the bot is never called.
- Callback exceptions propagate. A failed case creation should fail the webhook, so the
  platform retries and the message is not lost.
- `handle()` refuses async callbacks (it raises `TypeError`); use `handle_async()` for those.

Runnable examples:
- [examples/fastapi_webhook](../examples/fastapi_webhook/app.py)
- [examples/flask_webhook](../examples/flask_webhook/app.py)
- [no-code tools](../examples/n8n/README.md)

## LangChain

```console
pip install 'dutygate[langchain]'
```

```python
from dutygate.adapters.langchain import with_legal_gate

bot = with_legal_gate(prompt | model, gate, input_key="input", on_route=create_case)
bot.invoke({"input": "pls stop texting me"})  # → AIMessage(holding reply), model never called
```

- **What gets checked**: a `str` input, the value at `input[input_key]`, or the last human
  message in a message list or `PromptValue`.
- **On `route`** the wrapped runnable does not run. The holding reply comes back in the
  runnable's output type (an `AIMessage` for chat models, a `str` after `StrOutputParser`);
  pass `as_message=` to force one.
- **Methods**: `invoke`, `ainvoke`, `stream`, `astream` and `batch` are supported, and it
  composes with `|`.
- **Pass `on_route`.** Without it, a routed message gets the holding reply but no case is
  created anywhere, so the obligation can be lost.
- **Why not a callback**: LangChain callbacks can observe a chain but can't stop it.

Example: [examples/langchain_bot](../examples/langchain_bot/bot.py).

## Other stacks

Any other language, framework or no-code tool can call the HTTP sidecar; see
[sidecar.md](sidecar.md).
