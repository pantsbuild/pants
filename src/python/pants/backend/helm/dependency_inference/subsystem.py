# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from enum import Enum

from pants.option.option_types import EnumOption
from pants.option.subsystem import Subsystem
from pants.util.strutil import softwrap


class UnownedDependencyUsage(Enum):
    """What action to take when an inferred dependency is unowned."""

    RaiseError = "error"
    LogWarning = "warning"
    DoNothing = "ignore"


class UnownedDependencyError(Exception):
    """The inferred dependency does not have any owner."""


class HelmInferSubsystem(Subsystem):
    options_scope = "helm-infer"
    help = "Options controlling which dependencies will be inferred for Helm targets."

    unowned_dependency_behavior = EnumOption(
        default=UnownedDependencyUsage.LogWarning,
        help=softwrap(
            """
            How to handle inferred dependencies that don't have an inferrable owner.

            Usually when an import cannot be inferred, it represents an issue like Pants not being
            properly configured, e.g. targets not set up. Often, missing dependencies will result
            in confusing runtime errors where Docker images haven't been published,
            so this option can be helpful to error more eagerly.
            """
        ),
    )
