# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import filecmp
import logging
import os
import shutil
from collections import namedtuple

from pants.base.deprecated import deprecated_conditional
from pants.base.exceptions import TaskError
from pants.binaries.binary_tool import NativeTool
from pants.option.custom_types import dir_option, file_option
from pants.util.dirutil import safe_mkdir, safe_rmtree
from pants.util.memo import memoized_method, memoized_property
from pants.util.process_handler import subprocess

from pants.contrib.node.subsystems.yarnpkg_distribution import YarnpkgDistribution


logger = logging.getLogger(__name__)


class NodeDistribution(NativeTool):
  """Represents a self-bootstrapping Node distribution."""

  options_scope = 'node-distribution'
  name = 'node'
  default_version = 'v6.9.1'
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
    register('--supportdir', advanced=True, default='bin/node',
             removal_version='1.7.0.dev0', removal_hint='No longer supported.',
             help='Find the Node distributions under this dir.  Used as part of the path to '
                  'lookup the distribution with --binary-util-baseurls and --pants-bootstrapdir')
    register('--yarnpkg-version', advanced=True, default='v0.19.1', fingerprint=True,
             removal_version='1.7.0.dev0',
             removal_hint='Use --version in scope yarnpkg-distribution',
             help='Yarnpkg version to use.')

    register('--package-manager', advanced=True, default='npm', fingerprint=True,
             choices=NodeDistribution.VALID_PACKAGE_MANAGER_LIST.keys(),
             help='Default package manager config for repo. Should be one of {}'.format(
               NodeDistribution.VALID_PACKAGE_MANAGER_LIST.keys()))
    register('--eslint-setupdir', advanced=True, type=dir_option, fingerprint=True,
             help='Find the package.json and yarn.lock under this dir '
                  'for installing eslint and plugins.')
    register('--eslint-config', advanced=True, type=file_option, fingerprint=True,
             help='The path to the global eslint configuration file specifying all the rules')
    register('--eslint-ignore', advanced=True, type=file_option, fingerprint=True,
             help='The path to the global eslint ignore path')
    register('--eslint-version', default='4.15.0', fingerprint=True,
             help='Use this ESLint version.')

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
  def package_manager(self):
    return self.validate_package_manager(self.get_options().package_manager)

  @memoized_property
  def yarnpkg_version(self):
    return self._normalize_version(self.get_options().yarnpkg_version)

  @memoized_method
  def install_node(self):
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
  def install_yarnpkg(self, context=None):
    """Install the Yarnpkg distribution from pants support binaries.

    :param context: The context for this call. Remove this param in 1.7.0.dev0.
    :returns: The Yarnpkg distribution bin path.
    :rtype: string
    """
    yarnpkg_package_path = YarnpkgDistribution.scoped_instance(self).select(context=context)
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

      :param kwargs: Any extra keyword arguments to pass along to `subprocess.Popen`.
      :returns: A handle to the running command.
      :rtype: :class:`subprocess.Popen`
      """
      env, kwargs = self._prepare_env(kwargs)
      logger.debug('Running command {}'.format(self.cmd))
      return subprocess.Popen(self.cmd, env=env, **kwargs)

    def check_output(self, **kwargs):
      """Runs this command returning its captured stdout.

      :param kwargs: Any extra keyword arguments to pass along to `subprocess.Popen`.
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
    node_module_bin_dir = 'node_modules/.bin'
    extra_paths = []
    for t in tool_installations:
      extra_paths.append(t())
    if node_paths:
      for node_path in node_paths:
        if not node_path.endswith(node_module_bin_dir):
          node_path = os.path.join(node_path, node_module_bin_dir)
        extra_paths.append(node_path)
    return self.Command(executable=tool_executable, args=args, extra_paths=extra_paths)

  def node_command(self, args=None, node_paths=None):
    """Creates a command that can run `node`, passing the given args to it.

    :param list args: An optional list of arguments to pass to `node`.
    :param list node_paths: An optional list of paths to node_modules.
    :returns: A `node` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    # NB: We explicitly allow no args for the `node` command unlike the `npm` command since running
    # `node` with no arguments is useful, it launches a REPL.
    return self._command_gen([self.install_node], 'node', args=args, node_paths=node_paths)

  def npm_command(self, args, node_paths=None):
    """Creates a command that can run `npm`, passing the given args to it.

    :param list args: A list of arguments to pass to `npm`.
    :param list node_paths: An optional list of paths to node_modules.
    :returns: An `npm` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    return self._command_gen([self.install_node], 'npm', args=args, node_paths=node_paths)

  def yarnpkg_command(self, args, node_paths=None, context=None):
    """Creates a command that can run `yarnpkg`, passing the given args to it.

    :param list args: A list of arguments to pass to `yarnpkg`.
    :param list node_paths: An optional list of paths to node_modules.
    :param context: The context for this call. Remove this param in 1.7.0.dev0.
    :returns: An `yarnpkg` command that can be run later.
    :rtype: :class:`NodeDistribution.Command`
    """
    # TODO: In 1.7.0.dev0, remove this helper func and use self._install_yarnpkg directly.
    def install_yarnpkg():
      return self.install_yarnpkg(context=context)
    return self._command_gen(
      [self.install_node, install_yarnpkg], 'yarnpkg', args=args, node_paths=node_paths)

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
