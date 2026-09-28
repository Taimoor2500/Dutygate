from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from .schema import RedactionRule


def luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class Redactor:
    """Applies a pack's redaction rules, in order, before anything leaves the process."""

    def __init__(self, rules: Sequence[RedactionRule]) -> None:
        self._rules = [
            (re.compile(r.pattern), r.replacement or f"[{r.name.upper()}]", r.luhn) for r in rules
        ]

    def redact(self, text: str) -> str:
        for pattern, replacement, luhn in self._rules:
            # A callable replacement stops re from interpreting backslashes in the pack's text.
            text = pattern.sub(_replacer(replacement, luhn), text)
        return text


_DIGIT_GROUP = re.compile(r"\d+")


def _luhn_spans(text: str, replacement: str) -> str:
    """Redact every run of whole digit groups inside ``text`` that forms a Luhn-valid number.

    A greedy pattern also swallows neighbouring digits ("4111 1111 1111 1111 123" with a CVV),
    so the full match can fail the checksum while a card sits inside it.
    """
    groups = list(_DIGIT_GROUP.finditer(text))
    for i in range(len(groups)):
        for j in range(len(groups) - 1, i - 1, -1):  # longest window first
            digits = "".join(g.group(0) for g in groups[i : j + 1])
            if luhn_valid(digits):
                start, end = groups[i].start(), groups[j].end()
                return text[:start] + replacement + _luhn_spans(text[end:], replacement)
    return text


def _replacer(replacement: str, luhn: bool) -> Callable[[re.Match[str]], str]:
    def sub(m: re.Match[str]) -> str:
        if luhn:
            return _luhn_spans(m.group(0), replacement)
        return replacement

    return sub
