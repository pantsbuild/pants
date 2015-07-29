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

  @classmethod
  def product_types(cls):
    return ['gopath']

  def __init__(self, *args, **kwargs):
    super(GoTask, self).__init__(*args, **kwargs)

    self._gopath = self.workdir
    for dir in ('src', 'pkg', 'bin'):
      safe_mkdir(os.path.join(self._gopath, dir))

  def execute(self):
    targets = self.context.targets(self.is_go_source)
    self._symlink(targets)
    self.context.products.safe_create_data('gopath', lambda: defaultdict(str))
    for target in targets:
      self.context.products.get_data('gopath')[target] = self._gopath

  def _symlink(self, targets):
    for target in targets:
      basedir = get_basedir(target.target_base)
      basedir_link = os.path.join(self._gopath, 'src', basedir)
      if not os.path.islink(basedir_link):
        basedir_abs = os.path.join(get_buildroot(), basedir)
        os.symlink(basedir_abs, basedir_link)
