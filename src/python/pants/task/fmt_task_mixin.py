# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.task.target_restriction_mixins import (
  DeprecatedSkipAndDeprecatedTransitiveGoalOptionsRegistrar,
  HasSkipAndDeprecatedTransitiveGoalOptionsMixin,
)


class FmtTaskMixin(HasSkipAndDeprecatedTransitiveGoalOptionsMixin):
  """A mixin to combine with code formatting tasks."""
  goal_options_registrar_cls = DeprecatedSkipAndDeprecatedTransitiveGoalOptionsRegistrar
  target_filtering_enabled = True
