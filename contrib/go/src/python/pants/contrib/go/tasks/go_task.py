# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import sys

from pants.backend.core.tasks.task import Task
from pants.base.exceptions import TaskError

from pants.contrib.go.subsystems.go_distribution import GoDistribution
from pants.contrib.go.targets.go_binary import GoBinary
from pants.contrib.go.targets.go_library import GoLibrary
from pants.contrib.go.targets.go_local_source import GoLocalSource
from pants.contrib.go.targets.go_remote_library import GoRemoteLibrary


class GoTask(Task):

  @classmethod
  def global_subsystems(cls):
    # TODO(John Sirois): Actualy use the GoDistribution.Factory to create/run go commands.
    return super(GoTask, cls).global_subsystems() + (GoDistribution.Factory,)

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
    self._go_dist = None

  @property
  def go_dist(self):
    if self._go_dist is None:
      self._go_dist = GoDistribution.Factory.global_instance().create()
    return self._go_dist

  @property
  def goos_goarch(self):
    """Returns concatenated $GOOS and $GOARCH environment variables, separated by an underscore.

    Useful for locating where the Go compiler is placing binaries ("$GOPATH/pkg/$GOOS_$GOARCH").
    """
    if self._goos_goarch is None:
      self._goos_goarch = '{goos}_{goarch}'.format(goos=self._lookup_go_env_var('GOOS'),
                                                   goarch=self._lookup_go_env_var('GOARCH'))
    return self._goos_goarch

  def _lookup_go_env_var(self, var):
    return self.go_dist.create_go_cmd('env', args=[var]).check_output().strip()

  def global_import_id(self, go_remote_lib):
    """Returns the global import identifier of the given GoRemoteLibrary.

    A Go global import identifier is the "url" used to "go get" the remote library.
    Example: "github.com/user/mylib".

    A GoRemoteLibrary's global identifier is the relative path from the source
    root of all 3rd party Go packages to the BUILD file declaring the GoRemoteLibrary.
    """
    return os.path.relpath(go_remote_lib.address.spec_path,
                           go_remote_lib.target_base)
