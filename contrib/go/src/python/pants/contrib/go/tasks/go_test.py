# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.contrib.go.tasks.go_task import GoTask


class GoTest(GoTask):
  """Runs `go test` on Go packages.

  To run a library's tests, GoTest only requires GoSetupWorkspace to link in necessary source
  files. It does not require GoCompile to first compile the library to be tested -- in fact,
  GoTest will ignore any binaries in "$GOPATH/pkg/", because Go test files (which live in the
  package they are testing) are ignored in normal compilation, so Go test must compile
  everything from scratch.
  """

  @classmethod
  def register_options(cls, register):
    super(GoTest, cls).register_options(register)
    register('--build-and-test-flags', default='',
             help='Flags to pass in to `go test` tool.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoTest, cls).prepare(options, round_manager)
    round_manager.require_data('gopath')

  def execute(self):
    # Only executes the tests from the package specified by the target roots, so
    # we don't run the tests for _all_ dependencies of said package.
    for target in filter(self.is_go, self.context.target_roots):
      gopath = self.context.products.get_data('gopath')[target]
      self.run_go_cmd('test', gopath, target,
                      cmd_flags=self.get_options().build_and_test_flags.split(),
                      pkg_flags=self.get_passthru_args())
