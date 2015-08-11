# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

import pytest
from pants.util.contextutil import temporary_dir
from pants_test.contrib.go.tasks.go_tool import GoTool
from pants_test.pants_run_integration_test import PantsRunIntegrationTest

from pants.contrib.go.tasks.go_task import GoTask


class GoCompileIntegrationTest(PantsRunIntegrationTest):

  def test_go_compile_simple(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      args = ['compile',
              'contrib/go/examples/src/go/libA']
      pants_run = self.run_pants_with_workdir(args, workdir)
      self.assert_success(pants_run)
      if GoTool.go_installed():
        goos = subprocess.check_output(['go', 'env', 'GOOS']).strip()
        goarch = subprocess.check_output(['go', 'env', 'GOARCH']).strip()
        expected_files = set('contrib.go.examples.src.go.{libname}.{libname}/'
                             'pkg/{goos}_{goarch}/contrib/go/examples/src/go/{libname}.a'
                             .format(libname=libname, goos=goos, goarch=goarch)
                             for libname in ('libA', 'libB', 'libC', 'libD', 'libE'))
        self.assert_contains_exact_files(os.path.join(workdir, 'compile', 'go'),
                                         expected_files)
