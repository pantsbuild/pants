# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError
from pants.process.xargs import Xargs

from pants.contrib.go.subsystems.go_platform import GoPlatform
from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_local_source import GoLocalSource
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary


class GoTask(Task):

  @classmethod
  def global_subsystems(cls):
    return super(GoTask, cls).global_subsystems() + (GoPlatform, )

  @staticmethod
  def is_binary(target):
    return isinstance(target, GoBinary)

  @staticmethod
  def is_local_lib(target):
    return isinstance(target, GoLibrary)

  @staticmethod
  def is_remote_lib(target):
    return isinstance(target, GoRemoteLibrary)

  @staticmethod
  def is_local_src(target):
    return isinstance(target, GoLocalSource)

  @staticmethod
  def is_go(target):
    return isinstance(target, (GoLocalSource, GoRemoteLibrary))

  def __init__(self, *args, **kwargs):
    super(GoTask, self).__init__(*args, **kwargs)
    self._goos_goarch = None

  @property
  def goos_goarch(self):
    if self._goos_goarch is None:
      def get_env_var(var):
        p = subprocess.Popen(['go', 'env', var],
                             stdout=subprocess.PIPE)
        out, _ = p.communicate()
        return out
      self._goos_goarch = get_env_var('GOOS').strip() + '_' + get_env_var('GOARCH').strip()
    return self._goos_goarch

  def global_import_id(self, go_remote_lib):
    """Returns the global import identifier of the given GoRemoteLibrary.

    A Go global import identifier is the "url" used to "go get" the remote library.
    Example: "github.com/user/mylib".

    A GoRemoteLibrary's global identifier is the relative path from the source
    root of all 3rd party Go packages to the BUILD file declaring the GoRemoteLibrary.
    """
    return os.path.relpath(go_remote_lib.address.spec_path,
                           go_remote_lib.target_base)

  def run_go_cmd(self, cmd, gopath, target, cmd_flags=[], pkg_flags=[]):
    """Runs a Go command on a target from within a Go workspace.

    :param cmd string: Go command to execute, e.g. 'test' for `go test`
    :param gopath string: $GOPATH which points to a valid Go workspace from which
                          to run the command.
    :param target Target: A Go package whose source the command will execute on.
    :param cmd_flags list<str>: Command line flags to pass to command.
    :param pkg_flags list<str>: Command line flags to pass to target package.
    """
    os.environ['GOPATH'] = gopath
    if self.is_remote_lib(target):
      pkg_path = self.global_import_id(target)
    else:
      pkg_path = target.address.spec_path
    cmd = ['go', cmd] + cmd_flags + [pkg_path] + pkg_flags
    res = Xargs.subprocess(cmd).execute([])
    if res != 0:
      raise TaskError('`{cmd}` exited non-zero ({res})'
                      .format(cmd=' '.join(cmd), res=res))
