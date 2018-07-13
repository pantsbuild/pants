# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from abc import abstractmethod

from colors import green, red, yellow
from pants.base.exceptions import TaskError
from pants.task.task import QuietTaskMixin
from pants.util.process_handler import subprocess
from twitter.common.collections import OrderedSet

from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoInteropTask(QuietTaskMixin, GoWorkspaceTask):
  class MissingArgsError(TaskError):
    """Indicates missing go targets or missing pass-through arguments."""

  @classmethod
  def supports_passthru_args(cls):
    return True

  def execute(self, **kwargs):
    # NB: kwargs are for testing and pass-through to underlying subprocess process spawning.

    go_targets = OrderedSet(target for target in self.context.target_roots if self.is_go(target))
    args = self.get_passthru_args()
    if not go_targets or not args:
      msg = (yellow('The pants `{goal}` goal expects at least one go target and at least one '
                    'pass-through argument to be specified, call with:\n') +
             green('  ./pants {goal} {targets} -- {args}')
             .format(goal=self.options_scope,
                     targets=(green(' '.join(t.address.reference() for t in go_targets))
                              if go_targets else red('[missing go targets]')),
                     args=green(' '.join(args)) if args else red('[missing pass-through args]')))
      raise self.MissingArgsError(msg)

    go_path = OrderedSet()
    import_paths = OrderedSet()
    for target in go_targets:
      self.ensure_workspace(target)
      go_path.add(self.get_gopath(target))
      import_paths.add(target.import_path)

    self.execute_with_go_env(os.pathsep.join(go_path), list(import_paths), args, **kwargs)

  @abstractmethod
  def execute_with_go_env(self, go_path, import_paths, args, **kwargs):
    """Subclasses should execute the go interop task in the given environment.

    :param string go_path: The pre-formatted $GOPATH for the environment.
    :param list import_paths: The import paths for all the go targets specified in the environment.
    :param list args: The pass through arguments for the command to run in the go environment.
    :param **kwargs: Any additional `subprocess` keyword-args; for testing.
    """


class GoEnv(GoInteropTask):
  """Runs an arbitrary command in a go workspace defined by zero or more go targets."""

  def execute_with_go_env(self, go_path, import_paths, args, **kwargs):
    cmd = ' '.join(args)
    env = os.environ.copy()
    env.update(GOROOT=self.go_dist.goroot, GOPATH=go_path)
    process = subprocess.Popen(cmd, shell=True, env=env, **kwargs)
    result = process.wait()
    if result != 0:
      raise TaskError('{} failed with exit code {}'.format(cmd, result), exit_code=result)


class GoGo(GoInteropTask):
  """Runs an arbitrary go command against zero or more go targets."""

  def execute_with_go_env(self, go_path, import_paths, args, **kwargs):
    args = args + import_paths
    cmd = args.pop(0)
    go_cmd = self.go_dist.create_go_cmd(gopath=go_path, cmd=cmd, args=args)
    result = go_cmd.spawn(**kwargs).wait()
    if result != 0:
      raise TaskError('{} failed with exit code {}'.format(go_cmd, result), exit_code=result)
