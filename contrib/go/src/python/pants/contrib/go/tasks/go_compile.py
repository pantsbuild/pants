# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.util.dirutil import safe_mkdir

from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoCompile(GoWorkspaceTask):
  """Compiles a Go package into either a library binary or executable binary.

  GoCompile will populate the "bin/" and "pkg/" directories of a Go workspace (previously
  configured by GoSetupWorkspace) with executables and library binaries respectively.
  """

  @classmethod
  def register_options(cls, register):
    super(GoCompile, cls).register_options(register)
    register('--build-flags', default='',
             help='Build flags to pass to Go compiler.')

  @classmethod
  def product_types(cls):
    return ['exec_binary']

  def execute(self):
    self.context.products.safe_create_data('exec_binary', lambda: defaultdict(str))
    with self.invalidated(self.context.targets(self.is_go),
                          invalidate_dependents=True,
                          topological_order=True) as invalidation_check:
      # Maps each local/remote library target to its compiled binary.
      lib_binary_map = {}
      for vt in invalidation_check.all_vts:
        gopath = self.get_gopath(vt.target)
        if not vt.valid:
          print('invalid:', gopath)
          self.ensure_workspace(vt.target)
          self._sync_binary_dep_links(vt.target, gopath, lib_binary_map)
          self.run_go_cmd('install', gopath, vt.target,
                          cmd_flags=self.get_options().build_flags.split())
        if self.is_binary(vt.target):
          binary_path = os.path.join(gopath, 'bin', os.path.basename(vt.target.address.spec_path))
          self.context.products.get_data('exec_binary')[vt.target] = binary_path
        else:
          lib_binary_path = (vt.target.address.spec_path if self.is_local_lib(vt.target)
                             else self.global_import_id(vt.target))
          lib_binary_map[vt.target] = os.path.join(gopath, 'pkg',
                                                   self.goos_goarch,
                                                   lib_binary_path) + '.a'

  def _sync_binary_dep_links(self, target, gopath, lib_binary_map):
    """Syncs symlinks under gopath to the library binaries of target's transitive dependencies.

    :param target Target: Target whose transitive dependencies must be linked.
    :param gopath str: $GOPATH of target whose "pkg/" directory must be populated with links
                       to library binaries.
    :param lib_binary_map
           dict<Target, str>: Dictionary mapping a remote/local Go library to the path of the
                              compiled binary (the ".a" file) of the library.

    Required links to binary dependencies under gopath's "pkg/" dir are either created if
    non-existent, or refreshed if the link is older than the underlying binary. Any pre-existing
    links within gopath's "pkg/" dir that do not correspond to a transitive dependency of target
    are deleted.
    """
    required_links = set()
    for dep in target.closure():
      if dep == target:
        continue
      lib_binary = lib_binary_map[dep]
      lib_binary_link = os.path.join(gopath, os.path.relpath(lib_binary, self.get_gopath(dep)))
      safe_mkdir(os.path.dirname(lib_binary_link))
      if os.path.islink(lib_binary_link):
        if os.stat(lib_binary).st_mtime > os.lstat(lib_binary_link).st_mtime:
          # The binary under the link was updated after the link was created. Refresh
          # the link so the mtime (modification time) of the link is greater than the
          # mtime of the binary. This stops Go from needlessly re-compiling the library.
          os.unlink(lib_binary_link)
          os.symlink(lib_binary, lib_binary_link)
      else:
        os.symlink(lib_binary, lib_binary_link)
      required_links.add(lib_binary_link)
    self.remove_unused_links(os.path.join(gopath, 'pkg'), required_links)
