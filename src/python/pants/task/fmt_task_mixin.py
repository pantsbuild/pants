# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.task.target_restriction_mixins import (HasSkipAndTransitiveGoalOptionsMixin,
                                                  SkipAndTransitiveGoalOptionsRegistrar)


class FmtTaskMixin(HasSkipAndTransitiveGoalOptionsMixin):
  """A mixin to combine with code formatting tasks."""
  goal_options_registrar_cls = SkipAndTransitiveGoalOptionsRegistrar
  target_filtering_enabled = True
