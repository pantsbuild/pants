# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.goal_options_mixin import GoalOptionsMixin
from pants.task.target_restriction_mixins import (HasSkipAndTransitiveOptionsMixin,
                                                  SkipAndTransitiveOptionsRegistrarBase)


class FmtGoalOptionsRegistrar(SkipAndTransitiveOptionsRegistrarBase):
  options_scope = 'fmt'


class FmtTaskMixin(GoalOptionsMixin, HasSkipAndTransitiveOptionsMixin):
  """A mixin to combine with code formatting tasks."""
  goal_options_registrar_cls = FmtGoalOptionsRegistrar
