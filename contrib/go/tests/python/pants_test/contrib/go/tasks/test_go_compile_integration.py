# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import subsystem_instance

from pants.contrib.go.subsystems.go_distribution import GoDistribution


class GoCompileIntegrationTest(PantsRunIntegrationTest):

  def test_go_compile_simple(self):
    with self.temporary_workdir() as workdir:
      args = ['compile',
              'contrib/go/examples/src/go/libA']
      pants_run = self.run_pants_with_workdir(args, workdir)
      self.assert_success(pants_run)
      with subsystem_instance(GoDistribution.Factory) as factory:
        go_dist = factory.create()
        goos = go_dist.create_go_cmd('env', args=['GOOS']).check_output().strip()
        goarch = go_dist.create_go_cmd('env', args=['GOARCH']).check_output().strip()
        expected_files = set('contrib.go.examples.src.go.{libname}.{libname}/'
                             'pkg/{goos}_{goarch}/{libname}.a'
                             .format(libname=libname, goos=goos, goarch=goarch)
                             for libname in ('libA', 'libB', 'libC', 'libD', 'libE'))
        self.assert_contains_exact_files(os.path.join(workdir, 'compile', 'go'),
                                         expected_files)

  def test_go_compile_cgo(self):
    args = ['compile', 'contrib/go/examples/src/go/cgo']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
