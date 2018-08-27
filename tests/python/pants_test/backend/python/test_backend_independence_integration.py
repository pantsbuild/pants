# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BackendIndependenceTest(PantsRunIntegrationTest):
  """Verifies that this backend works with no other backends present."""

  @classmethod
  def hermetic(cls):
    return True

  def test_independent_test_run(self):
    pants_run = self.run_pants(
      command=['test', 'examples/tests/python/example_test/hello/greet'],
      config={
        'GLOBAL': {
          'pythonpath': [],
          'backend_packages': ['pants.backend.python'],
        }
      }
    )
    self.assert_success(pants_run)
