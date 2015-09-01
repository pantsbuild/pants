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


class GoDistribution(object):
  """Represents a self-bootstrapping Go distribution."""

  class Factory(Subsystem):
    options_scope = 'go-distribution'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register('--supportdir', advanced=True, default='bin/go',
               help='Find the go distributions under this dir.  Used as part of the path to lookup '
                    'the distribution with --binary-util-baseurls and --pants-bootstrapdir')
      register('--version', advanced=True, default='1.5',
               help='Go distribution version.  Used as part of the path to lookup the distribution '
                    'with --binary-util-baseurls and --pants-bootstrapdir')

    def create(self):
      # NB: create is an instance method to allow the user to choose global or scoped.
      # It's not unreasonable to imagine multiple go versions in play; for example: when
      # transitioning from the 1.x series to the 2.x series.
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return GoDistribution(binary_util, options.supportdir, options.version)

  def __init__(self, binary_util, relpath, version):
    self._binary_util = binary_util
    self._relpath = relpath
    self._version = version

  @property
  def version(self):
    """Returns the version of the Go distribution.

    :returns: The Go distribution version number string.
    :rtype: string
    """
    return self._version

  @memoized_property
  def goroot(self):
    """Returns the $GOROOT for this go distribution.

    :returns: The Go distribution $GOROOT.
    :rtype: string
    """
    go_distribution = self._binary_util.select_binary(self._relpath, self.version, 'go.tar.gz')
    distribution_workdir = os.path.dirname(go_distribution)
    outdir = os.path.join(distribution_workdir, 'unpacked')
    if not os.path.exists(outdir):
      with temporary_dir(root_dir=distribution_workdir) as tmp_dist:
        TGZ.extract(go_distribution, tmp_dist)
        os.rename(tmp_dist, outdir)
    return os.path.join(outdir, 'go')

  class GoCommand(namedtuple('GoCommand', ['cmdline', 'env'])):
    """Encapsulates a go command that can be executed."""

    @classmethod
    def _create(cls, goroot, cmd, gopath=None, args=None):
      env = OrderedDict(GOROOT=goroot)
      if gopath:
        env.update(GOPATH=gopath)
      return cls([os.path.join(goroot, 'bin', 'go'), cmd] + (args or []), env=env)

    def spawn(self, env=None, **kwargs):
      """
      :param dict env: A custom environment to launch the Go command in.  If `None` the current
                       environment is used.
      :param **kwargs: Keyword arguments to pass through to `subprocess.Popen`.
      :returns: A handle to the spawned go command subprocess.
      :rtype: :class:`subprocess.Popen`
      """
      env = (env or os.environ).copy()
      env.update(self.env)
      return subprocess.Popen(self.cmdline, env=env, **kwargs)

    def check_output(self, env=None, **kwargs):
      """Returns the output of the executed Go command.

      :param dict env: A custom environment to launch the Go command in.  If `None` the current
                       environment is used.
      :param **kwargs: Keyword arguments to pass through to `subprocess.check_output`.
      :return str: Output of Go command.
      :raises subprocess.CalledProcessError: Raises if Go command fails.
      """
      env = (env or os.environ).copy()
      env.update(self.env)
      return subprocess.check_output(self.cmdline, env=env, **kwargs)

    def __str__(self):
      return (' '.join('{}={}'.format(k, v) for k, v in self.env.items()) +
              ' ' +
              ' '.join(self.cmdline))

  def create_go_cmd(self, cmd, gopath=None, args=None):
    """Creates a Go command that is optionally targeted to a Go workspace.

    :param string cmd: Go command to execute, e.g. 'test' for `go test`
    :param string gopath: An optional $GOPATH which points to a valid Go workspace from which to run
                          the command.
    :param list args: A list of arguments and flags to pass to the Go command.
    :returns: A go command that can be executed later.
    :rtype: :class:`GoDistribution.GoCommand`
    """
    return self.GoCommand._create(self.goroot, cmd, gopath=gopath, args=args)

  def execute_go_cmd(self, cmd, gopath=None, args=None, env=None,
                     workunit_factory=None, workunit_name=None, workunit_labels=None, **kwargs):
    """Runs a Go command that is optionally targeted to a Go workspace.

    If a `workunit_factory` is supplied the command will run in a work unit context.

    :param string cmd: Go command to execute, e.g. 'test' for `go test`
    :param string gopath: An optional $GOPATH which points to a valid Go workspace from which to run
                          the command.
    :param list args: An optional list of arguments and flags to pass to the Go command.
    :param dict env: A custom environment to launch the Go command in.  If `None` the current
                     environment is used.
    :param workunit_factory: An optional callable that can produce a `WorkUnit` context
    :param string workunit_name: An optional name for the work unit; defaults to the `cmd`
    :param list workunit_labels: An optional sequence of labels for the work unit.
    :param **kwargs: Keyword arguments to pass through to `subprocess.Popen`.
    :returns: A tuple of the exit code and the go command that was run.
    :rtype: (int, :class:`GoDistribution.GoCommand`)
    """
    go_cmd = self.GoCommand._create(self.goroot, cmd, gopath=gopath, args=args)
    if workunit_factory is None:
      return go_cmd.spawn(**kwargs).wait()
    else:
      name = workunit_name or cmd
      labels = [WorkUnitLabel.TOOL] + (workunit_labels or [])
      with workunit_factory(name=name, labels=labels, cmd=str(go_cmd)) as workunit:
        process = go_cmd.spawn(env=env,
                               stdout=workunit.output('stdout'),
                               stderr=workunit.output('stderr'),
                               **kwargs)
        returncode = process.wait()
        workunit.set_outcome(WorkUnit.SUCCESS if returncode == 0 else WorkUnit.FAILURE)
        return returncode, go_cmd
