# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.fs.archive import TGZ
from pants.util.memo import memoized_property

from pants.contrib.node.subsystems.command import command_gen
from pants.contrib.node.subsystems.mixins import (PACKAGE_MANAGER_NPM, PACKAGE_MANAGER_YARNPKG,
                                                  PackageManagerMixin)


logger = logging.getLogger(__name__)


class Tool(object):
  """Defines a third party tool dependency."""

  def __init__(self, name, version):
    self.name = name
    self.version = Tool._normalize_version(version)

  def _get_bin_dir(self):
    raise NotImplementedError

  @staticmethod
  def _normalize_version(version):
    # The versions reported by node and embedded in distribution package names are 'vX.Y.Z' and not
    # 'X.Y.Z'.
    return version if version.startswith('v') else 'v' + version

  def run_command(self, args, node_paths=None):
    """Returns a command to run arbituray commands with the bool.

    :param args: Args to be passed to the tool.
    :param node_paths: A list of path that should be included in $PATH when
      running the tool.
    """
    return command_gen(self, args, node_paths=node_paths)

  def _get_path_vars(self):
    return [self.bin_dir]

  @memoized_property
  def path_vars(self):
    """Returns a list of paths to be prepended to $PATH."""
    return self._get_path_vars()

  @memoized_property
  def bin_dir(self):
    """Returns path to directory that contains the tool binary."""
    return self._get_bin_dir()

  @memoized_property
  def bin_path(self):
    """Returns path to the tool binary."""
    return os.path.join(self.bin_dir, self.name)


class InstallableTool(Tool):
  """Defines a third party tool dependency that needs to be installed."""

  def __init__(
    self, name, version,
    binary_util=None, support_dir=None, relative_bin_path=None, archive_filename=None):
    super(InstallableTool, self).__init__(name, version)
    self._binary_util = binary_util
    self._supportdir = support_dir
    self._relative_bin_path = relative_bin_path
    self._archive_filename = archive_filename

  def unpack_package(self):
    tarball_filepath = self._binary_util.select_binary(
      supportdir=self._supportdir, version=self.version, name=self._archive_filename)
    logger.debug('Tarball for %s(%s): %s', self._supportdir, self.version, tarball_filepath)
    workdir = os.path.dirname(tarball_filepath)
    TGZ.extract(tarball_filepath, workdir, concurrency_safe=True)
    return os.path.join(workdir, self._relative_bin_path)


class NodeBinary(InstallableTool):
  def __init__(self, binary_util, supportdir, version):
    # Todo: https://github.com/pantsbuild/pants/issues/4431
    # This line depends on repacked node distribution.
    # Should change it from 'node/bin' to 'dist/bin'
    super(NodeBinary, self).__init__(
      'node', version,
      binary_util=binary_util,
      support_dir=supportdir,
      relative_bin_path='node/bin',
      archive_filename='node.tar.gz')

  def _get_bin_dir(self):
    return self.unpack_package()


class YarnBinary(PackageManagerMixin, InstallableTool):
  def __init__(self, binary_util, supportdir, version, node_binary):
    super(YarnBinary, self).__init__(
      PACKAGE_MANAGER_YARNPKG, version,
      binary_util=binary_util,
      support_dir=supportdir,
      relative_bin_path='dist/bin',
      archive_filename='yarnpkg.tar.gz')
    self._node_binary = node_binary

  def _get_path_vars(self):
    return [self._node_binary.bin_dir, self.bin_dir]

  def _get_bin_dir(self):
    return self.unpack_package()

  def _get_run_script_args(self):
    return ['run']

  def _get_installation_args(self, install_optional):
    return [] if install_optional else ['--ignore-optional']


# Note that npm is installed with node.  Since node is a prerequisite for npm, there is no need
# to install npm separately.
class NpmBinary(PackageManagerMixin, Tool):
  def __init__(self, node_binary):
    # We don't actually know the npm version since we always use the npm bundled with node.
    super(NpmBinary, self).__init__(PACKAGE_MANAGER_NPM, '0.0.0')
    self._node_binary = node_binary

  def _get_bin_dir(self):
    return self._node_binary.bin_dir

  def _get_run_script_args(self):
    return ['run-script']

  def _get_installation_args(self, install_optional):
    return ['install'] if install_optional else ['install', '--no-optional']
