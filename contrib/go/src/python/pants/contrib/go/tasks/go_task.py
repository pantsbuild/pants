# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs

from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_package import GoPackage
from pants.contrib.go.targets.go_remote_package import GoRemotePackage


class GoTask(Task):

  @staticmethod
  def is_binary(target):
    return isinstance(target, GoBinary)

  @staticmethod
  def is_go_source(target):
    return isinstance(target, (GoPackage, GoRemotePackage, GoBinary))

  def run_go_cmd(self, cmd, gopath, target):
    os.environ['GOPATH'] = gopath
    args = ['go', cmd, target.target_base]
    res = Xargs.subprocess(args).execute([])
    if res != 0:
      raise TaskError('`{args}` exited non-zero ({res})'
                      .format(args=' '.join(args), res=res))
