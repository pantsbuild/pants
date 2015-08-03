# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_mkdir

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary
from pants.contrib.go.tasks.go_task import GoTask


class GoSetupWorkspace(GoTask):
  """Sets up a standard Go workspace and links Go packages to the workspace.

  Enables the use of Go tools which require a $GOPATH and correctly organized
  "src/", "pkg/", and "bin/" directories (e.g. `go install` or `go test`)
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoSetupWorkspace, cls).prepare(options, round_manager)
    round_manager.require_data('go_remote_lib_src')

  @classmethod
  def product_types(cls):
    # Produces a $GOPATH pointing to a "filled in" Go workspace.
    return ['gopath']

  def execute(self):
    self.context.products.safe_create_data('gopath', lambda: defaultdict(str))
    with self.invalidated(self.context.targets(self.is_go),
                          invalidate_dependents=True) as invalidation_check:
      for vt in invalidation_check.all_vts:
        gopath = os.path.join(self.workdir, vt.id)
        if not vt.valid:
          for dir in ('bin', 'pkg', 'src'):
            safe_mkdir(os.path.join(gopath, dir))
          for target in vt.target.closure():
            if self.is_remote_lib(target):
              self._symlink_remote_lib(gopath, target)
            else:
              self._symlink_local_src(gopath, target)
        self.context.products.get_data('gopath')[vt.target] = gopath

  def _symlink_local_src(self, gopath, go_local_src):
    """Creates symlinks from the given gopath to the source files of the given local package.

    Also duplicates directory structure leading to source files of package within
    gopath, in order to provide isolation to the package.
    """
    src_dir = os.path.join(gopath, 'src', go_local_src.address.spec_path)
    safe_mkdir(src_dir)
    for src in go_local_src.sources_relative_to_buildroot():
      src_link = os.path.join(src_dir, os.path.basename(src))
      if not os.path.islink(src_link):
        os.symlink(os.path.join(get_buildroot(), src), src_link)

  def _symlink_remote_lib(self, gopath, go_remote_lib):
    """Creates a symlink from the given gopath to the directory of the given remote library."""
    # Transforms github.com/user/lib --> $GOPATH/src/github.com/user
    remote_lib_dir = os.path.join(gopath,
                                  'src',
                                  os.path.dirname(self.global_import_id(go_remote_lib)))
    safe_mkdir(remote_lib_dir)
    remote_lib_source_dir = self.context.products.get_data('go_remote_lib_src')[go_remote_lib]
    remote_lib_link = os.path.join(remote_lib_dir,
                                   os.path.basename(remote_lib_source_dir))
    if not os.path.islink(remote_lib_link):
      os.symlink(remote_lib_source_dir, remote_lib_link)
