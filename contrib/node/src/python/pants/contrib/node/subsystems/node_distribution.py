# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import subprocess
from collections import namedtuple

from pants.binaries.binary_util import BinaryUtil
from pants.fs.archive import TGZ
from pants.subsystem.subsystem import Subsystem
from pants.util.contextutil import temporary_dir
from pants.util.memo import memoized_property


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
      register('--package-manager', advanced=True, default='npm',
               help='Default package manager config for repo. Should be one of [npm,yarnpkg]')
      register('--yarnpkg-version', advanced=True, default='v0.19.1',
               help='Yarnpkg version. Used for binary utils')

    def create(self):
      # NB: create is an instance method to allow the user to choose global or scoped.
      # It's not unreasonable to imagine multiple Node versions in play; for example: when
      # transitioning from the 0.10.x series to the 0.12.x series.
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      # for o in options:
      #   logger.debug('NodeDistrybution.Factory.create options[%s]: %s', o, options[o])
      return NodeDistribution(
        binary_util, options.supportdir, options.version,
        package_manager=options.package_manager, yarnpkg_version=options.yarnpkg_version)

  @classmethod
  def _normalize_version(cls, version):
    # The versions reported by node and embedded in distribution package names are 'vX.Y.Z' and not
    # 'X.Y.Z'.
    return version if version.startswith('v') else 'v' + version

  def __init__(self, binary_util, relpath, version, package_manager, yarnpkg_version):
    self._binary_util = binary_util
    self._relpath = relpath
    self._version = self._normalize_version(version)
    package_manager = 'yarnpkg' if package_manager == 'yarn' else package_manager
    if package_manager not in ['npm', 'yarnpkg']:
      raise RuntimeError('Unknown package manager: %s' % package_manager)
    logger.info('Node.js version: %s package manager from config: %s',
                self._version, package_manager)
    self.package_manager = package_manager
    self.yarnpkg_version = self._normalize_version(yarnpkg_version)

  @property
  def version(self):
    """Returns the version of the Node distribution.

    :returns: The Node distribution version number string.
    :rtype: string
    """
    return self._version

  @memoized_property
  def path(self):
    """Returns the root path of this node distribution.

    :returns: The Node distribution root path.
    :rtype: string
    """
    node_tar = self._binary_util.select_binary(self._relpath, self.version, 'node.tar.gz')
    logger.debug('Node tarball: %s', node_tar)
    node_work_dir = os.path.dirname(node_tar)
    node_umpacked_dir = os.path.join(node_work_dir, 'unpacked')
    if not os.path.exists(node_umpacked_dir):
      with temporary_dir(root_dir=node_work_dir) as tmp_dist:
        TGZ.extract(node_tar, tmp_dist)
        os.rename(tmp_dist, node_umpacked_dir)
    node_path = os.path.join(node_umpacked_dir, 'node')
    logger.debug('Node path: %s', node_path)
    return node_path

  @memoized_property
  def yarnpkg_path(self):
    """Returns the root path of yarnpkg distribution.

    :returns: The yarnpkg root path.
    :rtype: string
    """
    yarnpkg_tar = self._binary_util.select_binary(
      'bin/yarnpkg', self.yarnpkg_version, 'yarnpkg.tar.gz')
    logger.debug('Yarnpkg tarball: %s', yarnpkg_tar)
    yarnpkg_work_dir = os.path.dirname(yarnpkg_tar)
    yarnpkg_umpacked_dir = os.path.join(yarnpkg_work_dir, 'unpacked')
    if not os.path.exists(yarnpkg_umpacked_dir):
      with temporary_dir(root_dir=yarnpkg_work_dir) as tmp_dist:
        TGZ.extract(yarnpkg_tar, tmp_dist)
        os.rename(tmp_dist, yarnpkg_umpacked_dir)
    yarnpkg_path = os.path.join(yarnpkg_umpacked_dir, 'dist')
    logger.debug('Yarnpkg path: %s', yarnpkg_path)
    return yarnpkg_path

  class Command(namedtuple('Command', ['bin_dir_path', 'executable', 'args'])):
    """Describes a command to be run using a Node distribution."""

    @property
    def cmd(self):
      """The command line that will be executed when this command is spawned.

      :returns: The full command line used to spawn this command as a list of strings.
      :rtype: list
      """
      return [os.path.join(self.bin_dir_path, self.executable)] + self.args

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
      env['PATH'] = (self.bin_dir_path + os.path.pathsep + env['PATH']
                     if env.get('PATH', '') else self.bin_dir_path)
      return env, kwargs

    def run(self, **kwargs):
      """Runs this command.

      :param **kwargs: Any extra keyword arguments to pass along to `subprocess.Popen`.
      :returns: A handle to the running command.
      :rtype: :class:`subprocess.Popen`
      """
      env, kwargs = self._prepare_env(kwargs)
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

  def node_command(self, args=None):
    """Creates a command that can run `node`, passing the given args to it.

    :param list args: An optional list of arguments to pass to `node`.
    :returns: A `node` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    # NB: We explicitly allow no args for the `node` command unlike the `npm` command since running
    # `node` with no arguments is useful, it launches a REPL.
    return self._create_command('node', args)

  def npm_command(self, args):
    """Creates a command that can run `npm`, passing the given args to it.

    :param list args: A list of arguments to pass to `npm`.
    :returns: An `npm` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    return self._create_command('npm', args)

  def yarnpkg_command(self, args):
    """Creates a command that can run `yarnpkg`, passing the given args to it.

    :param list args: A list of arguments to pass to `yarnpkg`.
    :returns: An `yarnpkg` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    return self.Command(
      bin_dir_path=os.path.join(self.yarnpkg_path, 'bin'), executable='yarnpkg', args=args or [])

  def _create_command(self, executable, args=None):
    return self.Command(os.path.join(self.path, 'bin'), executable, args or [])
