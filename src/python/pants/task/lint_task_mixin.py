# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.task.target_restriction_mixins import (
    DeprecatedSkipGoalOptionsRegistrar,
    HasSkipGoalOptionMixin,
)


class LintTaskMixin(HasSkipGoalOptionMixin):
    """A mixin to combine with lint tasks."""

    goal_options_registrar_cls = DeprecatedSkipGoalOptionsRegistrar
    target_filtering_enabled = True

    @property
    def act_transitively(self):
        return False
