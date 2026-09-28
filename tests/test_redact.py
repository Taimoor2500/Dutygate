import pytest

from dutygate.redact import Redactor, luhn_valid
from dutygate.schema import RedactionRule

EMAIL = RedactionRule(
    name="email", pattern=r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+", replacement="[EMAIL]"
)
CARD = RedactionRule(
    name="card_number", pattern=r"\b(?:\d[ -]?){12,18}\d\b", luhn=True, replacement="[CARD]"
)


@pytest.fixture
def redactor() -> Redactor:
    return Redactor([EMAIL, CARD])


def test_email(redactor: Redactor) -> None:
    assert redactor.redact("mail a.b+c@ex.co.uk now") == "mail [EMAIL] now"


def test_multiple_emails(redactor: Redactor) -> None:
    assert redactor.redact("x@y.com and z@w.org") == "[EMAIL] and [EMAIL]"


@pytest.mark.parametrize("card", ["4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111"])
def test_luhn_valid_card_redacted(redactor: Redactor, card: str) -> None:
    assert redactor.redact(f"my card {card} was charged") == "my card [CARD] was charged"


@pytest.mark.parametrize(
    "text",
    [
        "order 1234 5678 9012 3456 is late",  # 16 digits, fails Luhn
        "call me on +1 415 555 0100",
        "since 2026-09-28 nothing works",
        "ticket 12345",
    ],
)
def test_lookalike_numbers_untouched(redactor: Redactor, text: str) -> None:
    assert redactor.redact(text) == text


def test_non_ascii_rtl_emoji_preserved(redactor: Redactor) -> None:
    text = "أريد حذف بياناتي 😡 mail me x@y.com"
    assert redactor.redact(text) == "أريد حذف بياناتي 😡 mail me [EMAIL]"


def test_default_replacement_is_upper_name() -> None:
    r = Redactor([RedactionRule(name="order_id", pattern=r"ORD-\d+")])
    assert r.redact("see ORD-991") == "see [ORDER_ID]"


@pytest.mark.parametrize(
    "text",
    ["x" * 8000, "a.b" * 2700, "1" * 8000, "a1 " * 2700],
    ids=["letters", "dotted", "digits", "mixed"],
)
def test_reference_pack_redaction_is_linear_on_long_input(text: str) -> None:
    import time
    from pathlib import Path

    from dutygate.schema import load_policy

    pack = load_policy(Path(__file__).resolve().parents[1] / "packs" / "legal-triggers.yaml")
    r = Redactor(pack.redaction)
    started = time.perf_counter()
    r.redact(text)
    assert time.perf_counter() - started < 0.05


def test_email_inside_long_word_run() -> None:
    r = Redactor([EMAIL])
    assert r.redact("prefix" + "x" * 50 + "@example.com tail") == "[EMAIL] tail"


def test_no_rules_is_identity() -> None:
    assert Redactor([]).redact("anything x@y.com") == "anything x@y.com"


@pytest.mark.parametrize(
    ("digits", "valid"),
    [
        ("4111111111111111", True),
        ("1234567890123456", False),
        ("79927398713", False),
        ("4012888888881881", True),
        ("12a4", False),
    ],
)
def test_luhn(digits: str, valid: bool) -> None:
    assert luhn_valid(digits) is valid


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("card 4111 1111 1111 1111 123 thanks", "card [CARD] 123 thanks"),
        ("4111111111111111 12/25", "[CARD] 12/25"),
        ("ref 12 4111 1111 1111 1111", "ref 12 [CARD]"),
        ("4111-1111-1111-1111-99", "[CARD]-99"),
    ],
    ids=["cvv-after", "expiry-after", "digits-before", "dashed-suffix"],
)
def test_card_next_to_other_digits_still_redacted(
    redactor: Redactor, text: str, expected: str
) -> None:
    assert redactor.redact(text) == expected


def test_luhn_invalid_groups_stay_untouched(redactor: Redactor) -> None:
    for text in ["order 1234 5678 9012 3456 is late", "ids 1234 5678 9012 3456 789"]:
        assert redactor.redact(text) == text
