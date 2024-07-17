# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from enum import Enum

from pants.option.option_types import EnumOption
from pants.util.strutil import softwrap


class UnownedDependencyUsage(Enum):
    """What action to take when an inferred dependency is unowned."""

    RaiseError = "error"
    LogWarning = "warning"
    DoNothing = "ignore"


class UnownedDependencyUsageOption(EnumOption[UnownedDependencyUsage, UnownedDependencyUsage]):
    def __new__(
        cls, example_runtime_issue: str, how_to_ignore: str
    ) -> UnownedDependencyUsageOption:
        return super().__new__(
            cls,
            default=UnownedDependencyUsage.LogWarning,
            help=softwrap(
                f"""
                How to handle imports that don't have an inferrable owner.
    
                Usually when an import cannot be inferred, it represents an issue like Pants not being
                properly configured, e.g. targets not set up. Often, missing dependencies will result
                in confusing runtime errors like {example_runtime_issue}, so this option can be helpful
                to error more eagerly.
    
                To ignore any false positives, {how_to_ignore}
            """
            ),
        )
