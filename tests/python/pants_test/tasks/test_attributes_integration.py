# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestAttributesIntegration(PantsRunIntegrationTest):

  def test_platform(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      J = 'src/scala/org/pantsbuild/zinc:zinc'
      P = 'src/python/pants/goal:goal'
      pants_run = self.run_pants_with_workdir(['-q', 'attributes', J, P],
                                              workdir)
    data = json.loads(pants_run.stdout_data)
    self.assertEqual(data[J]['language'], 'scala')
    self.assertEqual(data[J]['platform'], 'jvm')
    self.assertEqual(data[P]['language'], 'python')
    self.assertEqual(data[P]['platform'], 'python')
