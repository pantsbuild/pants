# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import filecmp
import logging
import os
import shutil

from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TaskError
from pants.binaries.binary_tool import NativeTool
from pants.option.custom_types import dir_option, file_option
from pants.util.dirutil import safe_mkdir, safe_rmtree
from pants.util.memo import memoized_method, memoized_property

from pants.contrib.node.subsystems.command import command_gen
from pants.contrib.node.subsystems.package_managers import (PACKAGE_MANAGER_NPM,
                                                            PACKAGE_MANAGER_YARNPKG,
                                                            PACKAGE_MANAGER_YARNPKG_ALIAS,
                                                            VALID_PACKAGE_MANAGERS,
                                                            PackageManagerNpm,
                                                            PackageManagerYarnpkg)
from pants.contrib.node.subsystems.yarnpkg_distribution import YarnpkgDistribution


logger = logging.getLogger(__name__)


class NodeDistribution(NativeTool):
  """Represents a self-bootstrapping Node distribution."""

  options_scope = 'node-distribution'
  name = 'node'
  default_version = 'v8.11.3'
  archive_type = 'tgz'

  @classmethod
  def subsystem_dependencies(cls):
    # Note that we use a YarnpkgDistribution scoped to the NodeDistribution, which may itself
    # be scoped to a task.
    return (super(NodeDistribution, cls).subsystem_dependencies() +
            (YarnpkgDistribution.scoped(cls), ))

  @classmethod
  def register_options(cls, register):
    super(NodeDistribution, cls).register_options(register)
    register('--package-manager', advanced=True, default='npm', fingerprint=True,
             choices=VALID_PACKAGE_MANAGERS,
             help='Default package manager config for repo. Should be one of {}'.format(
               VALID_PACKAGE_MANAGERS))
    register('--eslint-setupdir', advanced=True, type=dir_option, fingerprint=True,
             help='Find the package.json and yarn.lock under this dir '
                  'for installing eslint and plugins.')
    register('--eslint-config', advanced=True, type=file_option, fingerprint=True,
             help='The path to the global eslint configuration file specifying all the rules')
    register('--eslint-ignore', advanced=True, type=file_option, fingerprint=True,
             help='The path to the global eslint ignore path')
    register('--eslint-version', default='4.15.0', fingerprint=True,
             help='Use this ESLint version.')
    register('--node-scope', advanced=True, fingerprint=True,
             help='Default node scope for repo. Scope groups related packages together.')

  @memoized_method
  def _get_package_managers(self):
    npm = PackageManagerNpm([self._install_node])
    yarnpkg = PackageManagerYarnpkg([self._install_node, self._install_yarnpkg])
    return {
      PACKAGE_MANAGER_NPM: npm,
      PACKAGE_MANAGER_YARNPKG: yarnpkg,
      PACKAGE_MANAGER_YARNPKG_ALIAS: yarnpkg,  # Allow yarn to be used as an alias for yarnpkg
    }

  def get_package_manager(self, package_manager=None):
    package_manager = package_manager or self.get_options().package_manager
    package_manager_obj = self._get_package_managers().get(package_manager)
    if not package_manager_obj:
      raise TaskError(
        'Unknown package manager: {}.\nValid values are {}.'.format(
          package_manager, list(NodeDistribution.VALID_PACKAGE_MANAGER_LIST.keys())
      ))
    return package_manager_obj

  @memoized_method
  def version(self, context=None):
    # The versions reported by node and embedded in distribution package names are 'vX.Y.Z'.
    # TODO: After the deprecation cycle is over we'll expect the values of the version option
    # to already include the 'v' prefix, so there will be no need to normalize, and we can
    # delete this entire method override.
    version = super(NodeDistribution, self).version(context)
    deprecated_conditional(
      lambda: not version.startswith('v'), entity_description='', removal_version='1.7.0.dev0',
      hint_message='value of --version in scope {} must be of the form '
                   'vX.Y.Z'.format(self.options_scope))
    return version if version.startswith('v') else 'v' + version

  @classmethod
  def _normalize_version(cls, version):
    # The versions reported by node and embedded in distribution package names are 'vX.Y.Z' and not
    # 'X.Y.Z'.
    return version if version.startswith('v') else 'v' + version

  @memoized_property
  def eslint_setupdir(self):
    return self.get_options().eslint_setupdir

  @memoized_property
  def eslint_version(self):
    return self.get_options().eslint_version

  @memoized_property
  def eslint_config(self):
    return self.get_options().eslint_config

  @memoized_property
  def eslint_ignore(self):
    return self.get_options().eslint_ignore

  @memoized_property
  def node_scope(self):
    return self.get_options().node_scope

  @memoized_method
  def _install_node(self):
    """Install the Node distribution from pants support binaries.

    :returns: The Node distribution bin path.
    :rtype: string
    """
    node_package_path = self.select()
    # Todo: https://github.com/pantsbuild/pants/issues/4431
    # This line depends on repacked node distribution.
    # Should change it from 'node/bin' to 'dist/bin'
    node_bin_path = os.path.join(node_package_path, 'node', 'bin')
    return node_bin_path

  @memoized_method
  def _install_yarnpkg(self):
    """Install the Yarnpkg distribution from pants support binaries.

    :returns: The Yarnpkg distribution bin path.
    :rtype: string
    """
    yarnpkg_package_path = YarnpkgDistribution.scoped_instance(self).select()
    yarnpkg_bin_path = os.path.join(yarnpkg_package_path, 'dist', 'bin')
    return yarnpkg_bin_path

  def node_command(self, args=None, node_paths=None):
    """Creates a command that can run `node`, passing the given args to it.

    :param list args: An optional list of arguments to pass to `node`.
    :param list node_paths: An optional list of paths to node_modules.
    :returns: A `node` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    # NB: We explicitly allow no args for the `node` command unlike the `npm` command since running
    # `node` with no arguments is useful, it launches a REPL.
    return command_gen([self._install_node], 'node', args=args, node_paths=node_paths)

  def _configure_eslinter(self, bootstrapped_support_path):
    logger.debug('Copying {setupdir} to bootstrapped dir: {support_path}'
                           .format(setupdir=self.eslint_setupdir,
                                   support_path=bootstrapped_support_path))
    safe_rmtree(bootstrapped_support_path)
    shutil.copytree(self.eslint_setupdir, bootstrapped_support_path)
    return True

  _eslint_required_files = ['yarn.lock', 'package.json']

  def eslint_supportdir(self, task_workdir):
    """ Returns the path where the ESLint is bootstrapped.
    
    :param string task_workdir: The task's working directory
    :returns: The path where ESLint is bootstrapped and whether or not it is configured
    :rtype: (string, bool)
    """
    bootstrapped_support_path = os.path.join(task_workdir, 'eslint')

    # TODO(nsaechao): Should only have to check if the "eslint" dir exists in the task_workdir
    # assuming fingerprinting works as intended.

    # If the eslint_setupdir is not provided or missing required files, then
    # clean up the directory so that Pants can install a pre-defined eslint version later on.
    # Otherwise, if there is no configurations changes, rely on the cache.
    # If there is a config change detected, use the new configuration.
    if self.eslint_setupdir:
      configured = all(os.path.exists(os.path.join(self.eslint_setupdir, f))
                       for f in self._eslint_required_files)
    else:
      configured = False
    if not configured:
      safe_mkdir(bootstrapped_support_path, clean=True)
    else:
      try:
        installed = all(filecmp.cmp(
          os.path.join(self.eslint_setupdir, f), os.path.join(bootstrapped_support_path, f))
        for f in self._eslint_required_files)
      except OSError:
        installed = False

      if not installed:
        self._configure_eslinter(bootstrapped_support_path)
    return bootstrapped_support_path, configured
