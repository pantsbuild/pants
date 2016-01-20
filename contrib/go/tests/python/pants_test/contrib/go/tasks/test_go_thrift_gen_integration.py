# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants_test.pants_run_integration_test import PantsRunIntegrationTest
from pants_test.subsystem.subsystem_util import subsystem_instance
from pants_test.testutils.file_test_util import contains_exact_files

from pants.contrib.go.subsystems.go_distribution import GoDistribution


class GoThriftGenIntegrationTest(PantsRunIntegrationTest):

  def test_go_thrift_gen_simple(self):
    with self.temporary_workdir() as workdir:
      args = ['gen',
              'contrib/go/testprojects/src/thrift/thrifttest:fleem']
      pants_run = self.run_pants_with_workdir(args, workdir)
      self.assert_success(pants_run)
      with subsystem_instance(GoDistribution.Factory) as factory:
        go_dist = factory.create()
        goos = go_dist.create_go_cmd('env', args=['GOOS']).check_output().strip()
        goarch = go_dist.create_go_cmd('env', args=['GOARCH']).check_output().strip()
        expected_files = set([
          'contrib.go.testprojects.src.thrift.thrifttest.fleem/c4e43b3a84a8/src/go/thrifttest/duck/constants.go',
          'contrib.go.testprojects.src.thrift.thrifttest.fleem/c4e43b3a84a8/src/go/thrifttest/duck/ttypes.go',
        ])
        self.assertTrue(contains_exact_files(os.path.join(workdir, 'gen', 'go-thrift'),
                                             expected_files, ignore_links=True))

  def test_go_thrift_gen_and_compile(self):
    with self.temporary_workdir() as workdir:
      args = ['compile',
              'contrib/go/testprojects/src/go/usethrift']
      pants_run = self.run_pants_with_workdir(args, workdir)

      self.assert_success(pants_run)
