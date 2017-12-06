# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class MypyIntegrationTest(PantsRunIntegrationTest):
  def test_mypy(self):
    cmd = [
      'mypy',
      'contrib/mypy/tests/python/pants_test/contrib/mypy::',
      '--',
      '--follow-imports=silent'
    ]
    if self.has_python_version('3'):
      # Python 3.x is available. Test that we see an error in this integration test.
      with self.pants_results(cmd) as pants_run:
        self.assert_success(pants_run)
    else:
      # Python 3.x was not found. Test whether mypy task fails for that reason.
      with self.pants_results(cmd) as pants_run:
        self.assert_failure(pants_run)
        self.assertTrue('Unable to find a Python 3.x interpreter (required for mypy)' in pants_run.stdout_data)
