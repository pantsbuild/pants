# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.task.target_restriction_mixins import (
    DeprecatedSkipAndDeprecatedTransitiveGoalOptionsRegistrar,
    HasSkipAndTransitiveGoalOptionsMixin,
)


class FmtGoalRegistrar(DeprecatedSkipAndDeprecatedTransitiveGoalOptionsRegistrar):
    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--only",
            type=str,
            default=None,
            fingerprint=True,
            advanced=True,
            help="Only run the specified formatter. Currently the only accepted values are "
            "`scalafix` or not setting any value.",
        )


class FmtTaskMixin(HasSkipAndTransitiveGoalOptionsMixin):
    """A mixin to combine with code formatting tasks."""

    goal_options_registrar_cls = FmtGoalRegistrar
    target_filtering_enabled = True
