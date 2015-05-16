# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.projects.base_project_integration_test import ProjectIntegrationTest
from pants_test.testutils.compile_strategy_utils import provide_compile_strategies


class ExamplesIntegrationTest(ProjectIntegrationTest):
  @provide_compile_strategies
  def tests_examples(self, strategy):
    pants_run = self.pants_test(strategy, ['examples::'])
    self.assert_success(pants_run)
