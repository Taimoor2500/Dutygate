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

## LangGraph

```console
pip install 'dutygate[langgraph]'
```

DutyGate becomes two nodes in your graph: one before the agent and, optionally, one after it.

```python
from langgraph.graph import END, START, StateGraph
from dutygate import Gate
from dutygate.adapters.langgraph import DutyGateState, after_gate, gate_node, outbound_node

graph = StateGraph(DutyGateState)  # or subclass it to add your own fields
graph.add_node("dutygate", gate_node(Gate.from_pack("legal-triggers"), on_route=create_case))
graph.add_node("agent", agent)
graph.add_node(
    "check_reply", outbound_node(Gate.from_pack("outbound-claims"), on_route=create_case)
)
graph.add_edge(START, "dutygate")
graph.add_conditional_edges("dutygate", after_gate("agent"))  # END on route
graph.add_edge("agent", "check_reply")
graph.add_edge("check_reply", END)
app = graph.compile()
```

- **`gate_node`** checks the latest human message and writes the decision to
  `state["dutygate"]`. On `route` it appends the holding reply, and `after_gate` ends the
  graph, so the agent never runs. `on_route` and `on_review` receive the decision and the
  text; they can be sync or async.
- **`outbound_node`** checks the agent's latest reply, with the customer's message as
  context. On `route` it replaces that reply in place (same message id) with the holding
  reply, so a risky reply never reaches the customer. Its decision goes to
  `state["dutygate_outbound"]`.
- **Invocation:** both nodes work with `invoke`, `ainvoke` and streaming, with or without a
  checkpointer. Each turn checks that turn's latest message.
- **Custom state:** use `messages_key=` and `state_key=` if your state names differ, and
  declare the decision keys in your state schema, since LangGraph rejects updates to
  undeclared keys.

Example: [examples/langgraph_bot](../examples/langgraph_bot/graph.py).

## Other stacks

Any other language, framework or no-code tool can call the HTTP sidecar; see
[sidecar.md](sidecar.md).
