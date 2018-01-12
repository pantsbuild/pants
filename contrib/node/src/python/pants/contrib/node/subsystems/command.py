# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from collections import namedtuple

from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


class Command(namedtuple('Command', ['executable', 'args', 'extra_paths'])):
  """Describes a command to be run using a Node distribution."""

  @property
  def cmd(self):
    """The command line that will be executed when this command is spawned.

    :returns: The full command line used to spawn this command as a list of strings.
    :rtype: list
    """
    return [self.executable.bin_path] + (self.args or [])

  def _prepare_env(self, kwargs):
    """Returns a modifed copy of kwargs['env'], and a copy of kwargs with 'env' removed.

    If there is no 'env' field in the kwargs, os.environ.copy() is used.
    env['PATH'] is set/modified to contain the Node distribution's bin directory at the front.

    :param kwargs: The original kwargs.
    :returns: An (env, kwargs) tuple containing the modified env and kwargs copies.
    :rtype: (dict, dict)
    """
    kwargs = kwargs.copy()
    env = kwargs.pop('env', os.environ).copy()
    env['PATH'] = os.path.pathsep.join(
      self.executable.path_vars +
      self.extra_paths +
      [env.get('PATH', '')])
    return env, kwargs

  def run(self, **kwargs):
    """Runs this command.

    :param **kwargs: Any extra keyword arguments to pass along to `subprocess.Popen`.
    :returns: A handle to the running command.
    :rtype: :class:`subprocess.Popen`
    """
    env, kwargs = self._prepare_env(kwargs)
    logger.debug('Running command {}'.format(self.cmd))
    return subprocess.Popen(self.cmd, env=env, **kwargs)

  def check_output(self, **kwargs):
    """Runs this command returning its captured stdout.

    :param **kwargs: Any extra keyword arguments to pass along to `subprocess.Popen`.
    :returns: The captured standard output stream of the command.
    :rtype: string
    :raises: :class:`subprocess.CalledProcessError` if the command fails.
    """
    env, kwargs = self._prepare_env(kwargs)
    return subprocess.check_output(self.cmd, env=env, **kwargs)

  def __str__(self):
    return ' '.join(self.cmd)


def command_gen(tool_executable, args=None, node_paths=None):
  """Generate a Command object with requires tools installed and paths setup.

  :param tool_executable: Name of the tool to be executed.
  :param list args: A list of arguments to be passed to the executable
  :param list node_paths: A list of path to node_modules.  node_modules/.bin will be appended
    to the run time path.
  :rtype: class: `NodeDistribution.Command`
  """
  NODE_MODULE_BIN_DIR = 'node_modules/.bin'
  extra_paths = []
  if node_paths:
    for node_path in node_paths:
      if not node_path.endswith(NODE_MODULE_BIN_DIR):
        node_path = os.path.join(node_path, NODE_MODULE_BIN_DIR)
      extra_paths.append(node_path)
  return Command(executable=tool_executable, args=args, extra_paths=extra_paths)
