# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs
from pants.util.dirutil import get_basedir, safe_mkdir

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_package import GoPackage
from pants.contrib.go.targets.go_remote_package import GoRemotePackage
from pants.contrib.go.tasks.go_task import GoTask


class GoCompile(GoTask):

  @classmethod
  def product_types(cls):
    return ['go_workspace']

  @staticmethod
  def is_compilable(target):
    return isinstance(target, (GoPackage, GoRemotePackage, GoBinary))

  def __init__(self, *args, **kwargs):
    super(GoTask, self).__init__(*args, **kwargs)

    self._go_workspace = self.workdir
    for dir in ('src', 'pkg', 'bin'):
      safe_mkdir(os.path.join(self._go_workspace, dir))

  def execute(self):
    targets = self.context.targets(self.is_compilable)
    self._symlink(targets)
    self.context.products.safe_create_data('go_workspace', lambda: defaultdict(str))
    for target in self.context.target_roots:
      self._install(target)
      self.context.products.get_data('go_workspace')[target] = self._go_workspace

  def _symlink(self, targets):
    for target in targets:
      basedir = get_basedir(target.target_base)
      basedir_link = os.path.join(self._go_workspace, 'src', basedir)
      if not os.path.islink(basedir_link):
        basedir_abs = os.path.join(get_buildroot(), basedir)
        os.symlink(basedir_abs, basedir_link)

  def _install(self, target):
    os.environ['GOPATH'] = self._go_workspace
    cmd = ['go', 'install', target.target_base]
    res = Xargs.subprocess(cmd).execute([])
    if res != 0:
      raise TaskError('`{cmd}` exited non-zero ({res})'
                      .format(cmd=' '.join(cmd), res=res))
