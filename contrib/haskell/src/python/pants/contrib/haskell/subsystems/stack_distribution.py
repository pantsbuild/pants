# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
from collections import OrderedDict, namedtuple

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import TGZ
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_property


class StackDistribution(object):
  """Represents a self-bootstrapping Stack distribution."""

  class Factory(Subsystem):
    options_scope = 'stack-distribution'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register('--supportdir', advanced=True, default='bin/stack',
               help='Find the stack distributions under this dir.  Used as part of the path to '
                    'lookup the distribution with --binary-util-baseurls and --pants-bootstrapdir')
      register('--version', advanced=True, default='0.1.6.0',
               help='Stack distribution version.  Used as part of the path to lookup the '
                    'distribution with --binary-util-baseurls and --pants-bootstrapdir')

    @classmethod
    def create(cls):
      binary_util = BinaryUtil.Factory.create()
      options = cls.global_instance().get_options()
      return StackDistribution(binary_util, options.supportdir, options.version)

  def __init__(self, binary_util, relpath, version):
    self._binary_util = binary_util
    self._relpath = relpath
    self._version = version

  @property
  def version(self):
    """Returns the version of the Stack distribution.

    :returns: The Stack distribution version number string.
    :rtype: string
    """
    return self._version

  @memoized_property
  def base_dir(self):
    """Returns the base directory for this stack distribution.

    :returns: The stack distribution base directory.
    :rtype: string
    """
    stack_dist = self._binary_util.select_binary(self._relpath, self.version, 'stack.tar.gz')
    distribution_workdir = os.path.dirname(stack_dist)
    outdir = os.path.join(distribution_workdir, 'unpacked')
    if not os.path.exists(outdir):
      with temporary_dir(root_dir=distribution_workdir) as tmp_dist:
        TGZ.extract(stack_dist, tmp_dist)
        os.rename(tmp_dist, outdir)
    return os.path.join(outdir, 'stack')

  class StackCommand(namedtuple('StackCommand', ['cmdline', 'env'])):
    """Encapsulates a stack command that can be executed."""

    @classmethod
    def _create(cls, base_dir, cmd, stack_args=None, cmd_args=None):
      # TODO(John Sirois): Right now we take full control of stack flags and only allow the caller
      # to pass sub-command args.  Consider opening this up as the need arises.

      stack_exe = os.path.join(base_dir, 'stack')
      cmdline = [stack_exe]
      # Ensure we always run with a hermetic ghc
      cmdline.extend([
        '--no-system-ghc',
        '--install-ghc',
      ])

      if stack_args:
        cmdline.extend(stack_args)
      cmdline.append(cmd)
      if cmd_args:
        cmdline.extend(cmd_args)

      # We isolate our stack root from the default (~/.stack) using STACK_ROOT.
      # See: https://github.com/commercialhaskell/stack/issues/1178
      stack_root = os.path.join(base_dir, '.stack')
      env = OrderedDict(STACK_ROOT=stack_root)

      return cls(cmdline=cmdline, env=env)

    def spawn(self, env=None, **kwargs):
      """Spawn this stack command returning a handle to the spawned process.

      :param dict env: A custom environment to launch the stack command in.  If `None` the current
                       environment is used.
      :param **kwargs: Keyword arguments to pass through to `subprocess.Popen`.
      :returns: A handle to the spawned stack command subprocess.
      :rtype: :class:`subprocess.Popen`
      """
      env = (env or os.environ).copy()
      env.update(self.env)
      return subprocess.Popen(self.cmdline, env=env, **kwargs)

    def check_output(self, env=None, **kwargs):
      """Execute this stack command and return its output.

      :param dict env: A custom environment to launch the stack command in.  If `None` the current
                       environment is used.
      :param **kwargs: Keyword arguments to pass through to `subprocess.check_output`.
      :return str: The standard output of the stack command.
      :raises subprocess.CalledProcessError: Raises if the stack command fails.
      """
      env = (env or os.environ).copy()
      env.update(self.env)
      return subprocess.check_output(self.cmdline, env=env, **kwargs)

    def __str__(self):
      return (' '.join('{}={}'.format(k, v) for k, v in self.env.items()) +
              ' ' +
              ' '.join(self.cmdline))

  def create_stack_cmd(self, cmd, stack_args=None, cmd_args=None):
    """Creates a stack command that can be executed later.

    :param string cmd: The stack command to execute, e.g. 'setup' for `stack setup`
    :param list args: An optional list of arguments and flags to pass to the stack command.
    :returns: A stack command that can be executed later.
    :rtype: :class:`StackDistribution.StackCommand`
    """
    return self.StackCommand._create(
      self.base_dir,
      cmd,
      stack_args=stack_args,
      cmd_args=cmd_args)

  def execute_stack_cmd(self, cmd, stack_args=None, cmd_args=None,
                        workunit_factory=None, workunit_name=None, workunit_labels=None, **kwargs):
    """Runs a stack command.

    If a `workunit_factory` is supplied the command will run in a work unit context.

    :param string cmd: The stack command to execute, e.g. 'setup' for `stack setup`
    :param list args: An optional list of arguments and flags to pass to the stack command.
    :param workunit_factory: An optional callable that can produce a `WorkUnit` context
    :param string workunit_name: An optional name for the work unit; defaults to the `cmd`
    :param list workunit_labels: An optional sequence of labels for the work unit.
    :param **kwargs: Keyword arguments to pass through to `subprocess.Popen`.
    :returns: A tuple of the exit code and the stack command that was run.
    :rtype: (int, :class:`StackDistribution.StackCommand`)
    """
    stack_cmd = self.StackCommand._create(
      self.base_dir,
      cmd,
      stack_args=stack_args,
      cmd_args=cmd_args)
    if workunit_factory is None:
      return stack_cmd.spawn(**kwargs).wait()
    else:
      name = workunit_name or cmd
      labels = [WorkUnitLabel.TOOL] + (workunit_labels or [])
      with workunit_factory(name=name, labels=labels, cmd=str(stack_cmd)) as workunit:
        process = stack_cmd.spawn(stdout=workunit.output('stdout'),
                                  stderr=workunit.output('stderr'),
                                  **kwargs)
        returncode = process.wait()
        workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
        return returncode, stack_cmd
