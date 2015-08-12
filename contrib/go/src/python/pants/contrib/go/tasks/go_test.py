# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.workunit import WorkUnit

from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoTest(GoWorkspaceTask):
  """Runs `go test` on Go packages.

  To run a library's tests, GoTest only requires a Go workspace to be initialized
  (see GoWorkspaceTask) with links to necessary source files. It does not require
  GoCompile to first compile the library to be tested -- in fact, GoTest will ignore
  any binaries in "$GOPATH/pkg/", because Go test files (which live in the package
  they are testing) are ignored in normal compilation, so Go test must compile everything
  from scratch.
  """

  @classmethod
  def register_options(cls, register):
    super(GoTest, cls).register_options(register)
    register('--build-and-test-flags', default='',
             help='Flags to pass in to `go test` tool.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self):
    # Only executes the tests from the package specified by the target roots, so
    # we don't run the tests for _all_ dependencies of said package.
    for target in filter(self.is_local_src, self.context.target_roots):
      self.ensure_workspace(target)
      self._go_test(target)

  def _go_test(self, target):
    args = (self.get_options().build_and_test_flags.split()
            + [target.address.spec_path]
            + self.get_passthru_args())
    self.go_dist.execute_go_cmd('test', gopath=self.get_gopath(target), args=args,
                                workunit_factory=self.context.new_workunit,
                                workunit_labels=[WorkUnit.TEST])
