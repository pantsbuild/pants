# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class MetaRelocateIntegrationTest(PantsRunIntegrationTest):
  def test_meta_relocate(self):

    pre_dependees_run = self.run_pants(['dependees',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X'])

    pre_target_original_location_run = self.run_pants(['list',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X'])

    self.run_pants(['meta-relocate',
      '--to=testprojects/tests/java/org/pantsbuild/testproject/buildrefactor/x:X',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X'])

    post_target_new_location_run = self.run_pants(['list',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor/x:X'])

    self.run_pants(['meta-relocate',
      '--to=testprojects/tests/java/org/pantsbuild/testproject/buildrefactor',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor/x:X'])

    post_dependees_run = self.run_pants(['dependees',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X'])

    final_target_original_location_run = self.run_pants(['list',
      'testprojects/tests/java/org/pantsbuild/testproject/buildrefactor:X'])

    self.assertEquals(pre_dependees_run.stdout_data, post_dependees_run.stdout_data)
    self.assertEquals(pre_target_original_location_run.stdout_data, final_target_original_location_run.stdout_data)
    self.assertNotEqual(pre_target_original_location_run.stdout_data, post_target_new_location_run.stdout_data)

    