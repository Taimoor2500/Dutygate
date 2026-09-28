import math

import pytest

from dutygate.engine import evaluate, evaluate_async
from dutygate.errors import BackendError

from .helpers import StaticBackend, make_pack, zeros


def test_blank_message_continues_without_backend_call() -> None:
    backend = StaticBackend(zeros())
    for msg in ["", "   ", "\n\t"]:
        d = evaluate(make_pack(), msg, backend)
        assert d.action == "continue" and d.flags == () and d.error is None
    assert backend.requests == []


def test_too_long_uses_on_error_without_backend_call() -> None:
    backend = StaticBackend(zeros())
    d = evaluate(make_pack(limits={"max_message_chars": 5}), "123456", backend)
    assert d.action == "review"
    assert d.error is not None and d.error.code == "message_too_long"
    assert backend.requests == []


def test_limit_counts_code_points_not_bytes() -> None:
    pack = make_pack(limits={"max_message_chars": 10})
    backend = StaticBackend(zeros())
    assert evaluate(pack, "😡" * 10, backend).error is None
    d = evaluate(pack, "😡" * 11, backend)
    assert d.error is not None and d.error.code == "message_too_long"


def test_state_shape_and_redaction() -> None:
    backend = StaticBackend(zeros())
    evaluate(make_pack(), "mail x@y.com", backend)
    assert backend.requests[0].state == {"customer_message": "mail [EMAIL]"}
    evaluate(make_pack(), "hi", backend, channel="sms")
    assert backend.requests[1].state == {"customer_message": "hi", "channel": "sms"}


def test_custom_state_field() -> None:
    backend = StaticBackend(zeros())
    evaluate(make_pack(state_field="assistant_reply"), "done!", backend)
    assert backend.requests[0].state == {"assistant_reply": "done!"}


def test_recent_messages_last_n_redacted() -> None:
    backend = StaticBackend(zeros())
    pack = make_pack(context={"max_recent_messages": 2})
    evaluate(pack, "yes do that", backend, recent_messages=["one", "two a@b.co", "three"])
    assert backend.requests[0].state["recent_messages"] == ["two [EMAIL]", "three"]


def test_recent_messages_ignored_when_disabled() -> None:
    backend = StaticBackend(zeros())
    evaluate(make_pack(), "hi", backend, recent_messages=["earlier"])
    assert "recent_messages" not in backend.requests[0].state


def test_empty_recent_messages_omitted() -> None:
    backend = StaticBackend(zeros())
    evaluate(make_pack(context={"max_recent_messages": 3}), "hi", backend, recent_messages=[])
    assert "recent_messages" not in backend.requests[0].state


def test_one_backend_call_with_all_questions() -> None:
    backend = StaticBackend(zeros())
    evaluate(make_pack(), "hi", backend)
    assert len(backend.requests) == 1
    assert [q.id for q in backend.requests[0].questions] == ["q_a", "q_b", "q_c", "q_d"]


@pytest.mark.parametrize(
    "scores",
    [
        {"q_a": 0.1, "q_b": 0.1, "q_c": 0.1},  # missing q_d
        zeros(q_a="high"),  # type: ignore[arg-type]
        zeros(q_a=math.nan),
        zeros(q_a=math.inf),
        zeros(q_a=1.2),
        zeros(q_a=-0.1),
        zeros(q_a=True),  # bools are not scores
    ],
)
def test_malformed_scores(scores: dict[str, object]) -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(scores))  # type: ignore[arg-type]
    assert d.action == "review"
    assert d.flags == ()
    assert d.error is not None and d.error.code == "malformed_response"


def test_extra_keys_ignored() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend({**zeros(), "unexpected": 0.99}))
    assert d.action == "continue" and d.error is None


def test_integer_scores_accepted() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(zeros(q_a=1)))  # type: ignore[arg-type]
    assert d.action == "route"


def test_match_any_uses_max() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(zeros(q_c=0.05, q_d=0.35)))
    assert [(f.rule_id, f.confidence, f.level) for f in d.flags] == [("rule-c", 0.35, "confident")]


def test_match_all_uses_min() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(zeros(q_b=0.9, q_d=0.25)))
    # rule-b: min(0.9, 0.25) = 0.25 → grey; rule-c: max(0, 0.25) = 0.25 → confident (high 0.3? no)
    flags = {f.rule_id: (f.confidence, f.level) for f in d.flags}
    assert flags["rule-b"] == (0.25, "grey")
    assert flags["rule-c"] == (0.25, "grey")


def test_boundaries_inclusive() -> None:
    pack = make_pack()
    at_high = evaluate(pack, "hi", StaticBackend(zeros(q_a=0.5)))
    assert at_high.flags[0].level == "confident"
    at_low = evaluate(pack, "hi", StaticBackend(zeros(q_a=0.2)))
    assert at_low.flags[0].level == "grey"
    below = evaluate(pack, "hi", StaticBackend(zeros(q_a=0.1999)))
    assert below.flags == () and below.action == "continue"


def test_per_rule_threshold_override() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(zeros(q_c=0.3)))
    assert d.flags[0].rule_id == "rule-c" and d.flags[0].level == "confident"
    assert d.action == "route"


def test_ordering_confident_first_then_rule_order() -> None:
    # rule-a grey (0.3), rule-c confident (0.4 >= 0.3), rule-b grey (min 0.3)
    d = evaluate(make_pack(), "hi", StaticBackend(zeros(q_a=0.3, q_b=0.3, q_c=0.4, q_d=0.3)))
    assert [(f.rule_id, f.level) for f in d.flags] == [
        ("rule-c", "confident"),
        ("rule-a", "grey"),
        ("rule-b", "grey"),
    ]
    assert d.primary == "cat_c"
    assert d.action == "route"


def test_grey_only_is_review() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(zeros(q_a=0.3)))
    assert d.action == "review" and d.primary == "cat_a" and d.error is None


def test_all_clear_is_continue() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(zeros()))
    assert d.action == "continue" and d.primary is None and d.flags == ()


def test_flag_fields_and_rounding() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(zeros(q_a=0.912345678)))
    f = d.flags[0]
    assert (f.category, f.rule_id, f.queue, f.priority) == ("cat_a", "rule-a", "qa", "urgent")
    assert f.confidence == 0.9123


def test_rounding_happens_after_classification() -> None:
    # 0.49999 rounds to 0.5 but is below high: must stay grey.
    d = evaluate(make_pack(), "hi", StaticBackend(zeros(q_a=0.49999)))
    assert d.flags[0].level == "grey"


def test_backend_error_code_propagates() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(exc=BackendError("backend_timeout", "slow")))
    assert d.action == "review"
    assert d.error is not None and d.error.code == "backend_timeout"
    assert d.backend == {"name": "static", "model": None}


def test_unexpected_exception_is_internal_error(caplog: pytest.LogCaptureFixture) -> None:
    d = evaluate(make_pack(), "secret-sentinel text", StaticBackend(exc=RuntimeError("boom")))
    assert d.error is not None and d.error.code == "internal_error"
    assert "secret-sentinel" not in caplog.text


def test_on_error_route_respected() -> None:
    pack = make_pack(defaults={"on_error": "route"})
    d = evaluate(pack, "hi", StaticBackend(exc=BackendError("backend_unavailable", "down")))
    assert d.action == "route"


def test_metadata_fields() -> None:
    d = evaluate(make_pack(), "hi", StaticBackend(zeros()), conversation_id="c_9")
    assert d.conversation_id == "c_9"
    assert d.policy == {"name": "three", "version": "1.2.3"}
    assert d.backend == {"name": "static", "model": "static-1"}
    assert d.id.startswith("dec_")
    assert d.latency_ms >= 0


async def test_async_matches_sync() -> None:
    pack = make_pack()
    scores = zeros(q_a=0.3, q_c=0.9)
    a = await evaluate_async(pack, "hi", StaticBackend(scores), conversation_id="c")
    s = evaluate(pack, "hi", StaticBackend(scores), conversation_id="c")
    assert (a.action, a.primary, a.flags, a.error) == (s.action, s.primary, s.flags, s.error)


async def test_async_error_paths() -> None:
    pack = make_pack(limits={"max_message_chars": 3})
    assert (await evaluate_async(pack, " ", StaticBackend())).action == "continue"
    too_long = await evaluate_async(pack, "abcd", StaticBackend())
    assert too_long.error is not None and too_long.error.code == "message_too_long"
    boom = await evaluate_async(make_pack(), "hi", StaticBackend(exc=RuntimeError("x")))
    assert boom.error is not None and boom.error.code == "internal_error"
