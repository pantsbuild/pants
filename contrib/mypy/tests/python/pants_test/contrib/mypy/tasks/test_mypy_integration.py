# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class MypyIntegrationTest(PantsRunIntegrationTest):

  cmdline = ['--backend-packages=pants.contrib.mypy', 'lint']

  def test_valid_type_hints(self):
    result = self.run_pants([*self.cmdline, 'contrib/mypy/examples/src/python:valid'])
    self.assert_success(result)

  def test_invalid_type_hints(self):
    result = self.run_pants([*self.cmdline, 'contrib/mypy/examples/src/python:invalid'])
    self.assert_failure(result)
