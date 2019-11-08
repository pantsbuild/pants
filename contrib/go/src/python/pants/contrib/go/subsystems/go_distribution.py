# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from collections import OrderedDict, namedtuple

from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.binaries.binary_tool import NativeTool
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.util.memo import memoized_property


class GoReleaseUrlGenerator(BinaryToolUrlGenerator):

  _DIST_URL_FMT = 'https://storage.googleapis.com/golang/go{version}.{system_id}.tar.gz'

  _SYSTEM_ID = {
    'mac': 'darwin-amd64',
    'linux': 'linux-amd64',
  }

  def generate_urls(self, version, host_platform):
    system_id = self._SYSTEM_ID[host_platform.os_name]
    return [self._DIST_URL_FMT.format(version=version, system_id=system_id)]


class GoDistribution(NativeTool):
  """Represents a self-bootstrapping Go distribution."""

  options_scope = 'go-distribution'
  name = 'go'
  default_version = '1.8.3'
  archive_type = 'tgz'

  def get_external_url_generator(self):
    return GoReleaseUrlGenerator()

  @memoized_property
  def goroot(self):
    """Returns the $GOROOT for this go distribution.

    :returns: The Go distribution $GOROOT.
    :rtype: string
    """
    return os.path.join(self.select(), 'go')

  def go_env(self, gopath=None):
    """Return an env dict that represents a proper Go environment mapping for this distribution."""
    # Forcibly nullify the GOPATH if the command does not need one - this can prevent bad user
    # GOPATHs from erroring out commands; see: https://github.com/pantsbuild/pants/issues/2321.
    # NB: As of go 1.8, when GOPATH is unset (set to ''), it defaults to ~/go (assuming HOME is
    # set - and we can't unset that since it might legitimately be used by the subcommand); so we
    # set the GOPATH here to a valid value that nonetheless will fail to work if GOPATH is
    # actually used by the subcommand.
    no_gopath = os.devnull
    return OrderedDict(GOROOT=self.goroot, GOPATH=gopath or no_gopath)

  class GoCommand(namedtuple('GoCommand', ['cmdline', 'env'])):
    """Encapsulates a go command that can be executed."""

    @classmethod
    def _create(cls, goroot, cmd, go_env, args=None):
      return cls([os.path.join(goroot, 'bin', 'go'), cmd] + (args or []), env=go_env)

    def spawn(self, env=None, **kwargs):
      """
      :param dict env: A custom environment to launch the Go command in.  If `None` the current
                       environment is used.
      :param kwargs: Keyword arguments to pass through to `subprocess.Popen`.
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
      :param kwargs: Keyword arguments to pass through to `subprocess.check_output`.
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
    return self.GoCommand._create(self.goroot, cmd, go_env=self.go_env(gopath=gopath), args=args)

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
    :param kwargs: Keyword arguments to pass through to `subprocess.Popen`.
    :returns: A tuple of the exit code and the go command that was run.
    :rtype: (int, :class:`GoDistribution.GoCommand`)
    """
    go_cmd = self.create_go_cmd(cmd, gopath=gopath, args=args)
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
