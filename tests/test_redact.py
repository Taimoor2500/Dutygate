from pathlib import Path

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
    [
        "x" * 8000,
        "a.b" * 2700,
        "1" * 8000,
        "a1 " * 2700,
        "+1 " * 2700,
        "0 " * 4000,
        "GB12 " * 1600,
        "12-" * 2700,
        "QQ 1" * 2000,
    ],
    ids=[
        "letters",
        "dotted",
        "digits",
        "mixed",
        "plus",
        "zeros",
        "iban-like",
        "dashed",
        "nino-like",
    ],
)
def test_reference_pack_redaction_is_linear_on_long_input(text: str) -> None:
    import time

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


PACKS_DIR = Path(__file__).resolve().parents[1] / "packs"
REFERENCE_PACKS = ["legal-triggers", "outbound-claims"]


def reference_redactor(name: str = "legal-triggers") -> Redactor:
    from dutygate.schema import load_policy

    return Redactor(load_policy(PACKS_DIR / f"{name}.yaml").redaction)


def test_reference_packs_share_redaction_rules() -> None:
    from dutygate.schema import load_policy

    first, second = (load_policy(PACKS_DIR / f"{n}.yaml").redaction for n in REFERENCE_PACKS)
    assert first == second


@pytest.mark.parametrize("pack", REFERENCE_PACKS)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("call me on +1 415 555 0100", "call me on [PHONE]"),
        ("my number is +44 7700 900123.", "my number is [PHONE]."),
        ("whatsapp +971 50 123 4567 pls", "whatsapp [PHONE] pls"),
        ("ring +1 (415) 555-0100 today", "ring [PHONE] today"),
        ("+923001234567", "[PHONE]"),
        ("call 07700 900123 after 5", "call [PHONE] after 5"),
        ("my cell is 0300-1234567", "my cell is [PHONE]"),
        ("try 06 12 34 56 78", "try [PHONE]"),
        ("office (415) 555-0100 or 415.555.0100", "office [PHONE] or [PHONE]"),
    ],
)
def test_reference_packs_redact_phone_numbers(pack: str, text: str, expected: str) -> None:
    assert reference_redactor(pack).redact(text) == expected


@pytest.mark.parametrize("pack", REFERENCE_PACKS)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("refund to GB29 NWBK 6016 1331 9268 19 please", "refund to [IBAN] please"),
        ("IBAN: AE070331234567890123456", "IBAN: [IBAN]"),
        ("pay DE89370400440532013000 now", "pay [IBAN] now"),
    ],
)
def test_reference_packs_redact_ibans(pack: str, text: str, expected: str) -> None:
    assert reference_redactor(pack).redact(text) == expected


@pytest.mark.parametrize("pack", REFERENCE_PACKS)
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("my SSN is 123-45-6789", "my SSN is [NATIONAL_ID]"),
        ("NI number AB 12 34 56 C", "NI number [NATIONAL_ID]"),
        ("NI AB123456C", "NI [NATIONAL_ID]"),
        ("CNIC 35202-1234567-1 attached", "CNIC [NATIONAL_ID] attached"),
        ("Emirates ID 784-1990-1234567-1", "Emirates ID [NATIONAL_ID]"),
    ],
)
def test_reference_packs_redact_national_ids(pack: str, text: str, expected: str) -> None:
    assert reference_redactor(pack).redact(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "since 2026-09-28 nothing works",
        "on 28/09/2026 at 14:30",
        "ticket 12345",
        "order 1234 5678 9012 3456 is late",
        "order #88213409 never arrived",
        "you charged me $1,299.99 twice",
        "I paid 4,500 PKR on 12.09.2026",
        "tracking 1Z999AA10123456784",
        "version 0.1.0 of the app",
        "I have 3 lines and 2 phones",
        "between 9 and 5, 7 days a week",
        "room 101, floor 3",
        "ORDER ABCD 1234 is wrong",
    ],
)
def test_reference_pack_leaves_ordinary_numbers_alone(text: str) -> None:
    assert reference_redactor().redact(text) == text


def test_reference_pack_rules_compose() -> None:
    text = "I'm jane@x.com, +1 415 555 0100, card 4111 1111 1111 1111, SSN 123-45-6789"
    assert reference_redactor().redact(text) == (
        "I'm [EMAIL], [PHONE], card [CARD], SSN [NATIONAL_ID]"
    )
