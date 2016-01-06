# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ExeIntegrationTest(PantsRunIntegrationTest):
  def test_invalid_locale(self):
    pants_run = self.run_pants(command=['help'], extra_env={'LC_ALL': 'iNvALiD-lOcALe'})
    self.assert_failure(pants_run)
    self.assertIn(pants_run.stdout_data, 'Could not get a valid locale.')
    self.assertIn(pants_run.stdout_data, 'iNvALiD-lOcALe')
