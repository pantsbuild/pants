# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
from collections import namedtuple

from pants.base.exceptions import TaskError
from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import TGZ
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method
from pants.util.process_handler import subprocess


logger = logging.getLogger(__name__)


class NodeDistribution(object):
  """Represents a self-bootstrapping Node distribution."""

  class Factory(Subsystem):
    options_scope = 'node-distribution'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      super(NodeDistribution.Factory, cls).register_options(register)
      register('--supportdir', advanced=True, default='bin/node',
               help='Find the Node distributions under this dir.  Used as part of the path to '
                    'lookup the distribution with --binary-util-baseurls and --pants-bootstrapdir')
      register('--version', advanced=True, default='6.9.1',
               help='Node distribution version.  Used as part of the path to lookup the '
                    'distribution with --binary-util-baseurls and --pants-bootstrapdir')
      register('--package-manager', advanced=True, default='npm', fingerprint=True,
               choices=NodeDistribution.VALID_PACKAGE_MANAGER_LIST.keys(),
               help='Default package manager config for repo. Should be one of {}'.format(
                 NodeDistribution.VALID_PACKAGE_MANAGER_LIST.keys()))
      register('--yarnpkg-version', advanced=True, default='v0.19.1', fingerprint=True,
               help='Yarnpkg version. Used for binary utils')

    def create(self):
      # NB: create is an instance method to allow the user to choose global or scoped.
      # It's not unreasonable to imagine multiple Node versions in play; for example: when
      # transitioning from the 0.10.x series to the 0.12.x series.
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return NodeDistribution(
        binary_util, options.supportdir, options.version,
        package_manager=options.package_manager,
        yarnpkg_version=options.yarnpkg_version)

  PACKAGE_MANAGER_NPM = 'npm'
  PACKAGE_MANAGER_YARNPKG = 'yarnpkg'
  VALID_PACKAGE_MANAGER_LIST = {
    'npm': PACKAGE_MANAGER_NPM,
    'yarn': PACKAGE_MANAGER_YARNPKG
  }

  @classmethod
  def validate_package_manager(cls, package_manager):
    if package_manager not in cls.VALID_PACKAGE_MANAGER_LIST.keys():
      raise TaskError('Unknown package manager: %s' % package_manager)
    package_manager = cls.VALID_PACKAGE_MANAGER_LIST[package_manager]
    return package_manager

  @classmethod
  def _normalize_version(cls, version):
    # The versions reported by node and embedded in distribution package names are 'vX.Y.Z' and not
    # 'X.Y.Z'.
    return version if version.startswith('v') else 'v' + version

  def __init__(self, binary_util, supportdir, version, package_manager, yarnpkg_version):
    self._binary_util = binary_util
    self._supportdir = supportdir
    self._version = self._normalize_version(version)
    self.package_manager = self.validate_package_manager(package_manager=package_manager)
    self.yarnpkg_version = self._normalize_version(version=yarnpkg_version)
    logger.debug('Node.js version: %s package manager from config: %s',
                 self._version, package_manager)

  @property
  def version(self):
    """Returns the version of the Node distribution.

    :returns: The Node distribution version number string.
    :rtype: string
    """
    return self._version

  def unpack_package(self, supportdir, version, filename):
    tarball_filepath = self._binary_util.select_binary(
      supportdir=supportdir, version=version, name=filename)
    logger.debug('Tarball for %s(%s): %s', supportdir, version, tarball_filepath)
    work_dir = os.path.join(os.path.dirname(tarball_filepath), 'out')
    TGZ.extract(tarball_filepath, work_dir, concurrency_safe=True)
    return work_dir

  @memoized_method
  def install_node(self):
    """Install the Node distribution from pants support binaries.

    :returns: The Node distribution bin path.
    :rtype: string
    """
    node_package_path = self.unpack_package(
      supportdir=self._supportdir, version=self.version, filename='node.tar.gz')
    # Todo: https://github.com/pantsbuild/pants/issues/4431
    # This line depends on repacked node distribution.
    # Should change it from 'node/bin' to 'dist/bin'
    node_bin_path = os.path.join(node_package_path, 'node', 'bin')
    return node_bin_path

  @memoized_method
  def install_yarnpkg(self):
    """Install the Yarnpkg distribution from pants support binaries.

    :returns: The Yarnpkg distribution bin path.
    :rtype: string
    """
    yarnpkg_package_path = self.unpack_package(
      supportdir='bin/yarnpkg', version=self.yarnpkg_version, filename='yarnpkg.tar.gz')
    yarnpkg_bin_path = os.path.join(yarnpkg_package_path, 'dist', 'bin')
    return yarnpkg_bin_path

  class Command(namedtuple('Command', ['executable', 'args', 'extra_paths'])):
    """Describes a command to be run using a Node distribution."""

    @property
    def cmd(self):
      """The command line that will be executed when this command is spawned.

      :returns: The full command line used to spawn this command as a list of strings.
      :rtype: list
      """
      return [self.executable] + (self.args or [])

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
      env['PATH'] = os.path.pathsep.join(self.extra_paths + [env.get('PATH', '')])
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

  def _command_gen(self, tool_installations, tool_executable, args=None, node_paths=None):
    """Generate a Command object with requires tools installed and paths setup.

    :param list tool_installations: A list of functions to install required tools.  Those functions
      should take no parameter and return an installation path to be included in the runtime path.
    :param tool_executable: Name of the tool to be executed.
    :param list args: A list of arguments to be passed to the executable
    :param list node_paths: A list of path to node_modules.  node_modules/.bin will be appended
      to the run time path.
    :rtype: class: `NodeDistribution.Command`
    """
    NODE_MODULE_BIN_DIR = 'node_modules/.bin'
    extra_paths = []
    for t in tool_installations:
      extra_paths.append(t())
    if node_paths:
      for node_path in node_paths:
        if not node_path.endswith(NODE_MODULE_BIN_DIR):
          node_path = os.path.join(node_path, NODE_MODULE_BIN_DIR)
        extra_paths.append(node_path)
    return self.Command(executable=tool_executable, args=args, extra_paths=extra_paths)

  def node_command(self, args=None, node_paths=None):
    """Creates a command that can run `node`, passing the given args to it.

    :param list args: An optional list of arguments to pass to `node`.
    :returns: A `node` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    # NB: We explicitly allow no args for the `node` command unlike the `npm` command since running
    # `node` with no arguments is useful, it launches a REPL.
    return self._command_gen([self.install_node], 'node', args=args, node_paths=node_paths)

  def npm_command(self, args, node_paths=None):
    """Creates a command that can run `npm`, passing the given args to it.

    :param list args: A list of arguments to pass to `npm`.
    :returns: An `npm` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    return self._command_gen([self.install_node], 'npm', args=args, node_paths=node_paths)

  def yarnpkg_command(self, args, node_paths=None):
    """Creates a command that can run `yarnpkg`, passing the given args to it.

    :param list args: A list of arguments to pass to `yarnpkg`.
    :returns: An `yarnpkg` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    return self._command_gen(
      [self.install_node, self.install_yarnpkg], 'yarnpkg', args=args, node_paths=node_paths)
