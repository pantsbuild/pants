# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.backend.python.interpreter_selection_utils import has_python_version
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class MypyIntegrationTest(PantsRunIntegrationTest):
  def test_mypy(self):
    cmd = [
      'mypy',
      'contrib/mypy/tests/python/pants_test/contrib/mypy::',
      '--',
      '--follow-imports=silent'
    ]

    if any((has_python_version('3.{}'.format(v)) for v in (5, 6, 7, 8))):
      # Python 3.5+ is available. Test that we see an error in this integration test.
      with self.pants_results(cmd) as pants_run:
        self.assert_success(pants_run)
    else:
      # Python 3.5+ was not found. Test whether mypy task fails for that reason.
      with self.pants_results(cmd) as pants_run:
        self.assert_failure(pants_run)
        self.assertIn('Unable to find a Python >=3.5 interpreter (required for mypy)',
                      pants_run.stdout_data)
