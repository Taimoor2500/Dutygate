from hypothesis import given
from hypothesis import strategies as st

from dutygate.decision import ACTION_RANK
from dutygate.engine import decide

from .helpers import make_pack

PACK = make_pack()
RULE_INDEX = {r.id: i for i, r in enumerate(PACK.rules)}
score = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
scores_st = st.fixed_dictionaries({"q_a": score, "q_b": score, "q_c": score, "q_d": score})


@given(scores_st, st.sampled_from(["q_a", "q_b", "q_c", "q_d"]), score)
def test_raising_a_score_never_lowers_action(scores: dict[str, float], q: str, new: float) -> None:
    before, _, _ = decide(PACK, scores)
    raised = dict(scores)
    raised[q] = max(scores[q], new)
    after, _, _ = decide(PACK, raised)
    assert ACTION_RANK[after] >= ACTION_RANK[before]


@given(scores_st)
def test_flags_sorted_confident_first_then_rule_order(scores: dict[str, float]) -> None:
    _, primary, flags = decide(PACK, scores)
    keys = [(0 if f.level == "confident" else 1, RULE_INDEX[f.rule_id]) for f in flags]
    assert keys == sorted(keys)
    assert primary == (flags[0].category if flags else None)


@given(scores_st)
def test_confidences_in_range_and_action_consistent(scores: dict[str, float]) -> None:
    action, _, flags = decide(PACK, scores)
    assert all(0.0 <= f.confidence <= 1.0 for f in flags)
    assert (action == "continue") == (flags == ())
    assert (action == "route") == any(f.level == "confident" for f in flags)
