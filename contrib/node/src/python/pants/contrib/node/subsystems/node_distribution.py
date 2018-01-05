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
from pants.contrib.node.subsystems.command import command_gen
from pants.contrib.node.subsystem import tool_binaries
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
      register('--supportdir', advanced=True, default='bin',
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

  VALID_PACKAGE_MANAGER_LIST = {
    'npm': tool_binaries.PACKAGE_MANAGER_NPM,
    'yarn': tool_binaries.PACKAGE_MANAGER_YARNPKG,  # Allow yarn use as an alias for yarnpkg
    'yarnpkg': tool_binaries.PACKAGE_MANAGER_YARNPKG,
  }

  @classmethod
  def validate_package_manager(cls, package_manager):
    if package_manager not in cls.VALID_PACKAGE_MANAGER_LIST.keys():
      raise TaskError('Unknown package manager: %s' % package_manager)
    package_manager = cls.VALID_PACKAGE_MANAGER_LIST[package_manager]
    return package_manager

  def get_package_manager(package_manager=None):
    return (
      self.validate_package_manager(package_manager)
      if package_manager else self.package_manager
    )

  def __init__(self, binary_util, supportdir, version, package_manager, yarnpkg_version):
    self.package_manager = self.validate_package_manager(package_manager=package_manager)
    self._node_instance = tool_binaries.NodeBinary(binary_util, supportdir, version)
    self._package_managers_dict = {
      tool_binaries.PACKAGE_MANAGER_NPM: tool_binaries.NpmBinary(self._node_instance)
      tool_binaries.PACKAGE_MANAGER_YARNPKG: tool_binaries.YarnBianry(
        binary_util, supportdir, yarnpkg_version, self._node_instance)
    }
    logger.debug('Node.js version: %s package manager from config: %s', version, package_manager)

  def node_command(self, args=None, node_paths=None):
    """Creates a command that can run `node`, passing the given args to it.

    :param list args: An optional list of arguments to pass to `node`.
    :returns: A `node` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    # NB: We explicitly allow no args for the `node` command unlike the `npm` command since running
    # `node` with no arguments is useful, it launches a REPL.
    return command_gen(self._node_instance, args=args, node_paths=node_paths)

  def install_packages(self, install_optional=False, node_paths=None, package_manager=None):
    return self.get_package_manager(
      package_manager=package_manager
    ).install_packages(
      install_optional=install_optional,
      node_paths=node_paths
    )

  def run_script(self, script_name, script_args=None, node_paths=None, package_manager=None):
    return self.get_package_manager(
      package_manager=package_manager
    ).run_script(
      script_name,
      script_args=script_name,
      node_paths=node_paths
    )
