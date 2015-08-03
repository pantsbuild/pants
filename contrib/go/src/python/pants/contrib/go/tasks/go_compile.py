# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.util.dirutil import safe_mkdir

from pants.contrib.go.tasks.go_task import GoTask


class GoCompile(GoTask):
  """Compiles a Go package into either a library binary or executable binary."""

  @classmethod
  def register_options(cls, register):
    super(GoCompile, cls).register_options(register)
    register('--build-flags', default='',
             help='Build flags to pass to Go compiler.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoCompile, cls).prepare(options, round_manager)
    round_manager.require_data('gopath')

  @classmethod
  def product_types(cls):
    return ['exec_binary', 'lib_binaries']

  def execute(self):
    self.context.products.safe_create_data('exec_binary', lambda: defaultdict(str))
    with self.invalidated(self.context.targets(self.is_go_source),
                          invalidate_dependents=True,
                          topological_order=True) as invalidation_check:
      # Maps target to a list of library binary filepaths the target compiled.
      lib_binaries = defaultdict(list)

      for vt in invalidation_check.all_vts:
        gopath = self.context.products.get_data('gopath')[vt.target]

        if not vt.valid:
          for dep in vt.target.dependencies:
            dep_gopath = self.context.products.get_data('gopath')[dep]
            for lib_binary in lib_binaries[dep]:
              lib_binary_link = os.path.join(gopath, os.path.relpath(lib_binary, dep_gopath))
              safe_mkdir(os.path.dirname(lib_binary_link))
              os.symlink(lib_binary, lib_binary_link)
          self.run_go_cmd('install', gopath, vt.target,
                          cmd_flags=self.get_options().build_flags.split(),
                          pkg_flags=self.get_passthru_args())

        for root, _, files in os.walk(os.path.join(gopath, 'pkg')):
          lib_binaries[vt.target].extend((os.path.join(root, f) for f in files))

        if self.is_binary(vt.target):
          binary_path = os.path.join(gopath, 'bin', os.path.basename(vt.target.address.spec_path))
          self.context.products.get_data('exec_binary')[vt.target] = binary_path
