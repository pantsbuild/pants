# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
""""Registers trufflehog rules."""

from __future__ import annotations

from pants.backend.tools.trufflehog.rules import rules as trufflehog_rules


def rules() -> list:
    """Return trufflehog rules."""
    return trufflehog_rules()
