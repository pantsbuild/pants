# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess
from abc import abstractmethod, abstractproperty
from contextlib import contextmanager

from six import string_types
from twitter.common.collections import maybe_list

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import environment_as
from pants.util.dirutil import relativize_paths
from pants.util.meta import AbstractClass


logger = logging.getLogger(__name__)


class Executor(AbstractClass):
  """Executes java programs."""

  @staticmethod
  def _scrub_args(classpath, main, jvm_options, args, cwd):
    classpath = maybe_list(classpath)
    if not isinstance(main, string_types) or not main:
      raise ValueError('A non-empty main classname is required, given: {}'.format(main))
    jvm_options = maybe_list(jvm_options or ())
    args = maybe_list(args or ())
    return classpath, main, jvm_options, args, cwd

  class Error(Exception):
    """Indicates an error launching a java program."""

  class InvalidDistribution(ValueError):
    """Indicates an invalid Distribution was used to construct this runner."""

  class Runner(object):
    """A re-usable executor that can run a configured java command line."""

    @abstractproperty
    def executor(self):
      """Returns the executor this runner uses to run itself."""

    @property
    def cmd(self):
      """Returns a string representation of the command that will be run."""
      return ' '.join(self.command)

    @abstractproperty
    def command(self):
      """Returns a copy of the command line that will be run as a list of command line tokens."""

    @abstractmethod
    def run(self, stdout=None, stderr=None, cwd=None):
      """Runs the configured java command.

      If there is a problem executing tha java program subclasses should raise Executor.Error.
      Its guaranteed that all arguments are valid as documented in `execute`

      :param stdout: An optional stream to pump stdout to; defaults to `sys.stdout`.
      :param stderr: An optional stream to pump stderr to; defaults to `sys.stderr`.
      :param string cwd: optionally set the working directory
      """

  def __init__(self, distribution):
    """Constructs an Executor that can be used to launch java programs.

    :param distribution: a validated java distribution to use when launching java programs.
    """
    if not hasattr(distribution, 'java') or not hasattr(distribution, 'validate'):
      raise self.InvalidDistribution('A valid distribution is required, given: {}'
                                     .format(distribution))
    distribution.validate()
    self._distribution = distribution

  @property
  def distribution(self):
    """Returns the `Distribution` this executor runs via."""
    return self._distribution

  def runner(self, classpath, main, jvm_options=None, args=None, cwd=None):
    """Returns an `Executor.Runner` for the given java command."""
    return self._runner(*self._scrub_args(classpath, main, jvm_options, args, cwd=cwd))

  def execute(self, classpath, main, jvm_options=None, args=None, stdout=None, stderr=None,
      cwd=None):
    """Launches the java program defined by the classpath and main.

    :param list classpath: the classpath for the java program
    :param string main: the fully qualified class name of the java program's entry point
    :param list jvm_options: an optional sequence of options for the underlying jvm
    :param list args: an optional sequence of args to pass to the java program
    :param string cwd: optionally set the working directory

    Returns the exit code of the java program.
    Raises Executor.Error if there was a problem launching java itself.
    """
    executor = self.runner(classpath=classpath, main=main, jvm_options=jvm_options, args=args,
                           cwd=cwd)
    return executor.run(stdout=stdout, stderr=stderr, cwd=cwd)

  @abstractmethod
  def _runner(self, classpath, main, jvm_options, args, cwd=None):
    """Subclasses should return a `Runner` that can execute the given java main."""

  def _create_command(self, classpath, main, jvm_options, args, cwd=None):
    cmd = [self._distribution.java]
    cmd.extend(jvm_options)
    if cwd:
      classpath = relativize_paths(classpath, cwd)
    cmd.extend(['-cp', os.pathsep.join(classpath), main])
    cmd.extend(args)
    return cmd


class CommandLineGrabber(Executor):
  """Doesn't actually execute anything, just captures the cmd line."""

  def __init__(self, distribution):
    super(CommandLineGrabber, self).__init__(distribution=distribution)
    self._command = None  # Initialized when we run something.

  def _runner(self, classpath, main, jvm_options, args, cwd=None):
    self._command = self._create_command(classpath, main, jvm_options, args, cwd=cwd)

    class Runner(self.Runner):
      @property
      def executor(_):
        return self

      @property
      def command(_):
        return list(self._command)

      def run(_, stdout=None, stderr=None, cwd=None):
        return 0
    return Runner()

  @property
  def cmd(self):
    return self._command


class SubprocessExecutor(Executor):
  """Executes java programs by launching a jvm in a subprocess."""

  _SCRUBBED_ENV = {
      # We attempt to control the classpath for correctness, caching and invalidation reasons and
      # allowing CLASSPATH to influence would be a hermeticity leak
      'CLASSPATH': None,

      # We attempt to control jvm options and give user's explicit control in some cases as well.
      # In all cases we want predictable behavior - pants defaults, repo defaults, or user tweaks
      # specified on the command line.  In addition cli options can affect outputs; ie: class debug
      # info, target classfile version, etc - all breaking hermeticity.
      '_JAVA_OPTIONS': None,
      'JAVA_TOOL_OPTIONS': None
  }

  @classmethod
  @contextmanager
  def _maybe_scrubbed_env(cls):
    for env_var in cls._SCRUBBED_ENV:
      value = os.getenv(env_var)
      if value:
        logger.warn('Scrubbing {env_var}={value}'.format(env_var=env_var, value=value))
    with environment_as(**cls._SCRUBBED_ENV):
      yield

  def __init__(self, distribution):
    super(SubprocessExecutor, self).__init__(distribution=distribution)
    self._buildroot = get_buildroot()

  def _create_command(self, classpath, main, jvm_options, args, cwd=None):
    cwd = cwd or self._buildroot
    return super(SubprocessExecutor, self)._create_command(classpath, main, jvm_options,
                                                           args, cwd=cwd)

  def _runner(self, classpath, main, jvm_options, args, cwd=None):
    command = self._create_command(classpath, main, jvm_options, args, cwd=cwd)

    class Runner(self.Runner):
      @property
      def executor(_):
        return self

      @property
      def command(_):
        return list(command)

      def run(_, stdout=None, stderr=None, cwd=None):
        return self._spawn(command, stdout=stdout, stderr=stderr, cwd=cwd).wait()

    return Runner()

  def spawn(self, classpath, main, jvm_options=None, args=None, cwd=None, **subprocess_args):
    """Spawns the java program passing any extra subprocess kwargs on to subprocess.Popen.

    Returns the Popen process object handle to the spawned java program subprocess.
    """
    cmd = self._create_command(*self._scrub_args(classpath, main, jvm_options, args, cwd=cwd))
    return self._spawn(cmd, cwd, **subprocess_args)

  def _spawn(self, cmd, cwd=None, **subprocess_args):
    with self._maybe_scrubbed_env():
      cwd = cwd or self._buildroot
      logger.debug('Executing: {cmd} args={args} at cwd={cwd}'
                   .format(cmd=' '.join(cmd), args=subprocess_args, cwd=cwd))
      try:
        return subprocess.Popen(cmd, cwd=cwd, **subprocess_args)
      except OSError as e:
        raise self.Error('Problem executing {0}: {1}'.format(self._distribution.java, e))
