# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GoCheckstyleIntegrationTest(PantsRunIntegrationTest):

  def test_go_compile_go_with_readme_should_not_fail_checkstyle(self):
    args = ['compile', 'contrib/go/examples/src/go/with_readme']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
