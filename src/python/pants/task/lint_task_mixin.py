# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.target_restriction_mixins import (HasSkipAndTransitiveGoalOptionsMixin,
                                                  SkipAndTransitiveGoalOptionsRegistrar)


class LintTaskMixin(HasSkipAndTransitiveGoalOptionsMixin):
  """A mixin to combine with lint tasks."""
  goal_options_registrar_cls = SkipAndTransitiveGoalOptionsRegistrar
