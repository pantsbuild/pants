""""Registers trufflehog rules."""

from __future__ import annotations

from .rules import rules as trufflehog_rules


def rules() -> list:
    """Return trufflehog rules."""
    return trufflehog_rules()
