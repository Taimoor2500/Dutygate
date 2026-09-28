from __future__ import annotations

from .decision import Decision

# Admits no fault, promises no outcome, states no deadline, claims no completed action.
# Hosts should localize it and replace it with counsel-approved wording where they have it.
DEFAULT_HOLDING_REPLY = (
    "Thanks for your message. A member of our team will review it and follow up with you."
)


def default_holding_reply(decision: Decision) -> str:
    return DEFAULT_HOLDING_REPLY
