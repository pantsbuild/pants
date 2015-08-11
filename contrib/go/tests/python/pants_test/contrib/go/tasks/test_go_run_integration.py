# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pytest
from pants_test.contrib.go.tasks.go_tool import GoTool
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GoRunIntegrationTest(PantsRunIntegrationTest):

  @pytest.mark.skipif('not GoTool.go_installed()', reason='requires `go` command.')
  def test_go_run_simple(self):
    args = ['run',
            'contrib/go/examples/src/go/hello',
            '--',
            '-n=3']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
