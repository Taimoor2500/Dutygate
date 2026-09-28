"""A chatbot webhook in Flask (synchronous) with DutyGate in front of the reply step.

Run it:
    pip install dutygate flask
    TYPESAFE_API_KEY=... flask --app app run --port 8000

Offline, with the conformance fixtures:
    DUTYGATE_BACKEND=replay DUTYGATE_FIXTURES=../../conformance/cases.json \
    DUTYGATE_PACK=../../packs/legal-triggers.yaml flask --app app run --port 8000
"""

from __future__ import annotations

import os
from typing import Any

from flask import Flask, jsonify, request

from dutygate import Decision, Gate, ReplayBackend, load_policy
from dutygate.adapters.webhook import GatedHandler

CASES: list[dict[str, Any]] = []
REVIEWS: list[str] = []
RESCAN: list[str] = []


def load_gate() -> Gate:
    pack_path = os.environ.get("DUTYGATE_PACK", "packs/legal-triggers.yaml")
    if os.environ.get("DUTYGATE_BACKEND") == "replay":
        pack = load_policy(pack_path)
        return Gate(pack, ReplayBackend.from_conformance(os.environ["DUTYGATE_FIXTURES"], pack))
    return Gate.from_pack(pack_path)


def bot_reply(message: str) -> str:
    return f"(bot) You said: {message}"


def create_case(decision: Decision, message: str) -> None:
    CASES.append({"decision": decision.to_dict()})


def create_review_task(decision: Decision, message: str) -> None:
    REVIEWS.append(decision.id)


def enqueue_rescan(decision: Decision, message: str) -> None:
    RESCAN.append(message)


handler = GatedHandler(
    load_gate(),
    reply=bot_reply,
    on_route=create_case,
    on_review=create_review_task,
    on_gate_failure=enqueue_rescan,
)

app = Flask(__name__)


@app.post("/webhook")
def webhook() -> Any:
    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message:
        return jsonify({"error": "message is required"}), 400
    result = handler.handle(
        message, conversation_id=body.get("conversation_id"), channel=body.get("channel")
    )
    return jsonify({"reply": result.reply, "action": result.decision.action})
