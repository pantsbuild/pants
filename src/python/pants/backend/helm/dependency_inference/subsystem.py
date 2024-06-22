# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from enum import Enum
from functools import cached_property

from pants.option.option_types import EnumOption, StrListOption
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

    external_docker_images = StrListOption(
        default=[],
        help=softwrap(
            """
            Docker image names that are not provided by targets in this repository
            and should be ignored for calculating dependencies.

            For example, adding `python` to this setting
            will cause Pants to not try to find the target `python:3.10`
            in the following `helm_deployment`:

            ```
            helm_deployment(
                name="my-deployment",
                chart=":mychart",
                values={"container.image_ref": "python:3.10"},
            )
            ```

            Use the value '*' to disable this check.
            This will limit Pants's ability to warn on unknown docker images.
            """
        ),
    )

    @cached_property
    def external_base_images(self) -> set[str]:
        return set(self.external_docker_images)
