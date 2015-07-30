# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs

from pants.contrib.go.subsystems.go_platform import GoPlatform
from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_package import GoPackage
from pants.contrib.go.targets.go_remote_package import GoRemotePackage


class GoTask(Task):

  @classmethod
  def global_subsystems(cls):
    return super(GoTask, cls).global_subsystems() + (GoPlatform, )

  @staticmethod
  def is_binary(target):
    return isinstance(target, GoBinary)

  @staticmethod
  def is_go_remote_pkg(target):
    return isinstance(target, GoRemotePackage)

  @staticmethod
  def is_go_source(target):
    return isinstance(target, (GoPackage, GoRemotePackage, GoBinary))

  def global_import_id(self, go_remote_pkg):
    """Returns the global import identifier of the given GoRemotePackage.

    A Go global import identifier is the "url" used to "go get" the remote package.
    Example: "github.com/user/mylib".

    A GoRemotePackage's global identifier is the relative path from the configured
    "remote-pkg-root" to the BUILD file initializing the GoRemotePackage.
    """
    return os.path.relpath(go_remote_pkg.target_base,
                           GoPlatform.global_instance().remote_pkg_root)

  def run_go_cmd(self, cmd, gopath, target):
    """Runs a Go command on a target from within a Go workspace.

    :param cmd string: Go command to execute, e.g. 'test' for `go test`
    :param gopath string: $GOPATH which points to a valid Go workspace from which
                          to run the command.
    :param target Target: Either a GoPackage or GoBinary whose source the command
                          will execute upon.
    """
    os.environ['GOPATH'] = gopath
    args = ['go', cmd, target.target_base]
    res = Xargs.subprocess(args).execute([])
    if res != 0:
      raise TaskError('`{args}` exited non-zero ({res})'
                      .format(args=' '.join(args), res=res))
