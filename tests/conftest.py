import pytest


@pytest.fixture(autouse=True)
def _no_user_redaction_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a DUTYGATE_REDACTION_FILE from the developer's shell out of every test."""
    monkeypatch.delenv("DUTYGATE_REDACTION_FILE", raising=False)
