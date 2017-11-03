# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class MetaRenameIntegrationTest(PantsRunIntegrationTest):
  def test_meta_rename(self):

    pre_dependees = self.run_pants(['dependees',
      'testprojects/tests/java/org/pantsbuild/testproject/builrefactor:X'])

    self.run_pants(['meta-rename',
      '--from=testprojects/tests/java/org/pantsbuild/testproject/builrefactor:X',
      '--to=testprojects/tests/java/org/pantsbuild/testproject/builrefactor:Y',
      'testprojects/tests/java/org/pantsbuild/testproject/builrefactor:X'])

    post_dependees = self.run_pants(['dependees',
      'testprojects/tests/java/org/pantsbuild/testproject/builrefactor:Y'])

    self.run_pants(['meta-rename',
      '--from=testprojects/tests/java/org/pantsbuild/testproject/builrefactor:Y',
      '--to=testprojects/tests/java/org/pantsbuild/testproject/builrefactor:X',
      'testprojects/tests/java/org/pantsbuild/testproject/builrefactor:Y'])

    self.assertEquals(pre_dependees.stdout_data, post_dependees.stdout_data)
