# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class BuildozerIntegrationTest(PantsRunIntegrationTest):
  def test_buildozer_warn(self):
    buildozer_print_run = self.run_pants(['buildozer',
      '--command=print name',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X'])

    self.assertIn('WARN', buildozer_print_run.stderr_data)
    self.assertIn('... no changes were made', buildozer_print_run.stderr_data)
