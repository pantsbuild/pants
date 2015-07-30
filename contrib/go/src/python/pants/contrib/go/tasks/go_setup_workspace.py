# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.base.build_environment import get_buildroot
from pants.util.dirutil import get_basedir, safe_mkdir

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_package import GoPackage
from pants.contrib.go.targets.go_remote_package import GoRemotePackage
from pants.contrib.go.tasks.go_task import GoTask


class GoSetupWorkspace(GoTask):
  """Sets up a standard Go workspace and links Go packages to the workspace.

  Enables the use of Go tools which require a $GOPATH and correctly organized
  "src/", "pkg/", and "bin/" directories.
  """

  @classmethod
  def prepare(cls, options, round_manager):
    super(GoSetupWorkspace, cls).prepare(options, round_manager)
    round_manager.require_data('go_remote_pkg_source')

  @classmethod
  def product_types(cls):
    return ['gopath']

  def __init__(self, *args, **kwargs):
    super(GoTask, self).__init__(*args, **kwargs)

    self._gopath = self.workdir
    for dir in ('src', 'pkg', 'bin'):
      safe_mkdir(os.path.join(self._gopath, dir))

  def execute(self):
    self.context.products.safe_create_data('gopath', lambda: defaultdict(str))
    for target in self.context.targets(self.is_go_source):
      if self.is_go_remote_pkg(target):
        self._symlink_remote_pkg(target)
      else:
        self._symlink_local_pkg(target)
      self.context.products.get_data('gopath')[target] = self._gopath

  def _symlink_local_pkg(self, go_pkg):
    """Adds a symlink from the current Go workspace to the given local package.

    :param go_pkg: A local Go package -- either a GoPackage or GoBinary target.
    """
    basedir = get_basedir(go_pkg.target_base)
    basedir_link = os.path.join(self._gopath, 'src', basedir)
    if not os.path.islink(basedir_link):
      basedir_abs = os.path.join(get_buildroot(), basedir)
      os.symlink(basedir_abs, basedir_link)

  def _symlink_remote_pkg(self, go_remote_pkg):
    """Adds a symlink from the current Go workspace to the source of the given GoRemotePackage."""
    # Transforms github.com/user/lib --> $GOPATH/src/github.com/user
    remote_pkg_dir = os.path.join(self._gopath,
                                  'src',
                                  os.path.dirname(self.global_import_id(go_remote_pkg)))
    safe_mkdir(remote_pkg_dir)
    remote_pkg_source_dir = self.context.products.get_data('go_remote_pkg_source')[go_remote_pkg]
    remote_pkg_link = os.path.join(remote_pkg_dir,
                                   os.path.basename(remote_pkg_source_dir))
    if not os.path.islink(remote_pkg_link):
      os.symlink(remote_pkg_source_dir, remote_pkg_link)
