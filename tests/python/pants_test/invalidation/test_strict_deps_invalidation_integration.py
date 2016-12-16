# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class RunTrackerIntegrationTest(PantsRunIntegrationTest):

  TEST_SRC = 'testprojects/tests/java/org/pantsbuild/testproject/strictdeps'

  def test_strict_deps_false(self):
    with self.temporary_sourcedir() as tmp_src:
      src_dir = os.path.join(tmp_src, os.path.basename(self.TEST_SRC))
      shutil.copytree(self.TEST_SRC, src_dir)
      with self.temporary_workdir() as workdir:
        cmd = ['compile', '{}:A2'.format(src_dir)]
        pants_run = self.run_pants_with_workdir(command=cmd, workdir=workdir)
        self.assert_success(pants_run)

  def test_strict_deps_true(self):
    pass
