# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import global_subsystem_instance
from pants_test.testutils.file_test_util import contains_exact_files

from pants.contrib.go.subsystems.go_distribution import GoDistribution


class GoCompileIntegrationTest(PantsRunIntegrationTest):

  def test_go_compile_simple(self):
    with self.temporary_workdir() as workdir:
      args = ['compile',
              'contrib/go/examples/src/go/libA']
      pants_run = self.run_pants_with_workdir(args, workdir)
      self.assert_success(pants_run)
      go_dist = global_subsystem_instance(GoDistribution)
      goos = go_dist.create_go_cmd('env', args=['GOOS']).check_output().decode('utf-8').strip()
      goarch = go_dist.create_go_cmd('env', args=['GOARCH']).check_output().decode('utf-8').strip()
      expected_files = set('contrib.go.examples.src.go.{libname}.{libname}/'
                           'pkg/{goos}_{goarch}/{libname}.a'
                           .format(libname=libname, goos=goos, goarch=goarch)
                           for libname in ('libA', 'libB', 'libC', 'libD', 'libE'))
      self.assertTrue(contains_exact_files(os.path.join(workdir, 'compile', 'go'),
                                           expected_files, ignore_links=True))

  def test_go_compile_cgo(self):
    args = ['compile', 'contrib/go/examples/src/go/cgo']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_go_compile_with_remote_deps(self):
    args = ['compile', 'contrib/go/examples/src/go/server']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_go_compile_double_quoted_build_flags(self):
    args = ['compile',
            'contrib/go/examples/src/go/server',
            '--compile-go-build-flags="--ldflags \'-extldflags \"-static\"\'"']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_go_compile_single_quoted_build_flags(self):
    args = ['compile',
            'contrib/go/examples/src/go/server',
            '--compile-go-build-flags=\'--ldflags \'-extldflags "-static"\'\'']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)

  def test_go_compile_adjacent_single_double_quotes_build_flags(self):
    args = ['compile',
            'contrib/go/examples/src/go/server',
            '--compile-go-build-flags=\'-v -tags "netgo"\'']
    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
