"""A chatbot webhook in FastAPI with DutyGate in front of the reply step.

Run it:
    pip install 'dutygate[server]'
    TYPESAFE_API_KEY=... uvicorn app:app --port 8000

Try it offline with the conformance fixtures instead of TypeSafe:
    DUTYGATE_BACKEND=replay DUTYGATE_FIXTURES=../../conformance/cases.json \
    DUTYGATE_PACK=../../packs/legal-triggers.yaml uvicorn app:app --port 8000

    curl -d '{"message": "pls stop texting me"}' -H 'content-type: application/json' \
      localhost:8000/webhook
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from dutygate import Decision, Gate, ReplayBackend, load_policy
from dutygate.adapters.webhook import GatedHandler

CASES: list[dict[str, Any]] = []  # stand-in for your ticketing system
REVIEWS: list[dict[str, Any]] = []
RESCAN: list[str] = []


def load_gate() -> Gate:
    pack_path = os.environ.get("DUTYGATE_PACK", "packs/legal-triggers.yaml")
    if os.environ.get("DUTYGATE_BACKEND") == "replay":
        pack = load_policy(pack_path)
        return Gate(pack, ReplayBackend.from_conformance(os.environ["DUTYGATE_FIXTURES"], pack))
    return Gate.from_pack(pack_path)  # TypeSafe Jev, configured from the environment


async def bot_reply(message: str) -> str:
    return f"(bot) You said: {message}"  # your LLM call goes here


async def create_case(decision: Decision, message: str) -> None:
    for flag in decision.flags:
        CASES.append(
            {
                "queue": flag.queue,
                "priority": flag.priority,
                "category": flag.category,
                "decision_id": decision.id,
            }
        )


async def create_review_task(decision: Decision, message: str) -> None:
    REVIEWS.append({"decision_id": decision.id, "flags": [f.category for f in decision.flags]})


async def enqueue_rescan(decision: Decision, message: str) -> None:
    RESCAN.append(message)  # the gate could not judge it; scan again later


gate = load_gate()
handler = GatedHandler(
    gate,
    reply=bot_reply,
    on_route=create_case,
    on_review=create_review_task,
    on_gate_failure=enqueue_rescan,
)


@asynccontextmanager
async def lifespan(_: FastAPI):  # type: ignore[no-untyped-def]
    yield
    await gate.aclose()


app = FastAPI(lifespan=lifespan)


class Inbound(BaseModel):
    message: str
    conversation_id: str | None = None
    channel: str | None = None


@app.post("/webhook")
async def webhook(body: Inbound) -> dict[str, Any]:
    result = await handler.handle_async(
        body.message, conversation_id=body.conversation_id, channel=body.channel
    )
    return {"reply": result.reply, "action": result.decision.action}
