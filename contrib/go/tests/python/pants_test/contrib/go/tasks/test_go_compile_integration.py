# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest

from pants.contrib.go.tasks.go_task import GoTask


class GoCompileIntegrationTest(PantsRunIntegrationTest):

  def test_go_compile_simple(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      args = ['compile',
              'contrib/go/examples/src/go/libA']
      pants_run = self.run_pants_with_workdir(args, workdir)
      self.assert_success(pants_run)
      # TODO(cgibb): Is it appropriate to be calling a GoTask static method from
      # an integration test?
      try:
        goos_goarch = GoTask.lookup_goos_goarch()
      except OSError:
        # Go isn't installed -- just stop the test here.
        return
      expected_files = set('contrib.go.examples.src.go.{libname}.{libname}/'
                           'pkg/{goos_goarch}/contrib/go/examples/src/go/{libname}.a'
                           .format(libname=libname, goos_goarch=goos_goarch)
                           for libname in ('libA', 'libB', 'libC', 'libD', 'libE'))
      self.assert_contains_exact_files(os.path.join(workdir, 'compile', 'go'),
                                       expected_files)
