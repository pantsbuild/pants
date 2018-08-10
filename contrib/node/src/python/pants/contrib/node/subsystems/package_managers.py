# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from builtins import object

from pants.contrib.node.subsystems.command import command_gen


LOG = logging.getLogger(__name__)

PACKAGE_MANAGER_NPM = 'npm'
PACKAGE_MANAGER_YARNPKG = 'yarnpkg'
PACKAGE_MANAGER_YARNPKG_ALIAS = 'yarn'
VALID_PACKAGE_MANAGERS = [PACKAGE_MANAGER_NPM, PACKAGE_MANAGER_YARNPKG, PACKAGE_MANAGER_YARNPKG_ALIAS]


# TODO: Change to enum type when migrated to Python 3.4+
class PackageInstallationTypeOption(object):
  PROD = 'prod'
  DEV = 'dev'
  PEER = 'peer'
  BUNDLE = 'bundle'
  OPTIONAL = 'optional'
  NO_SAVE = 'not saved'


class PackageInstallationVersionOption(object):
  EXACT = 'exact'
  TILDE = 'tilde'


class PackageManager(object):
  """Defines node package manager functionalities."""

  def __init__(self, name, tool_installations):
    self.name = name
    self.tool_installations = tool_installations

  def _get_installation_args(self, install_optional, production_only, force, frozen_lockfile):
    """Returns command line args for installing package.

    :param install_optional: True to request install optional dependencies.
    :param production_only: True to only install production dependencies, i.e.
      ignore devDependencies.
    :param force: True to force re-download dependencies.
    :param frozen_lockfile: True to disallow automatic update of lock files.
    :rtype: list of strings
    """
    raise NotImplementedError

  def _get_run_script_args(self):
    """Returns command line args to run a package.json script.

    :rtype: list of strings
    """
    raise NotImplementedError

  def _get_add_package_args(self, package, type_option, version_option):
    """Returns command line args to add a node pacakge.

    :rtype: list of strings
    """
    raise NotImplementedError()

  def run_command(self, args=None, node_paths=None):
    """Returns a command that when executed will run an arbitury command via package manager."""
    return command_gen(
      self.tool_installations,
      self.name,
      args=args,
      node_paths=node_paths
    )

  def install_module(
    self,
    install_optional=False,
    production_only=False,
    force=False,
    frozen_lockfile=True,
    node_paths=None):
    """Returns a command that when executed will install node package.

    :param install_optional: True to install optional dependencies.
    :param production_only: True to only install production dependencies, i.e.
      ignore devDependencies.
    :param force: True to force re-download dependencies.
    :param frozen_lockfile: True to disallow automatic update of lock files.
    :param node_paths: A list of path that should be included in $PATH when
      running installation.
    """
    args=self._get_installation_args(
      install_optional=install_optional,
      production_only=production_only,
      force=force,
      frozen_lockfile=frozen_lockfile)
    return self.run_command(args=args, node_paths=node_paths)

  def run_script(self, script_name, script_args=None, node_paths=None):
    """Returns a command to execute a package.json script.

    :param script_name: Name of the script to name.  Note that script name 'test'
      can be used to run node tests.
    :param script_args: Args to be passed to package.json script.
    :param node_paths: A list of path that should be included in $PATH when
      running the script.
    """
    # TODO: consider add a pants.util function to manipulate command line.
    package_manager_args = self._get_run_script_args()
    package_manager_args.append(script_name)
    if script_args:
      package_manager_args.append('--')
      package_manager_args.extend(script_args)
    return self.run_command(args=package_manager_args, node_paths=node_paths)

  def add_package(
    self,
    package,
    node_paths=None, 
    type_option=PackageInstallationTypeOption.PROD,
    version_option=None):
    """Returns a command that when executed will add a node package to current node module.

    :param package: string.  A valid npm/yarn package description.  The accepted forms are
      package-name, package-name@version, package-name@tag, file:/folder, file:/path/to.tgz
      https://url/to.tgz
    :param node_paths: A list of path that should be included in $PATH when
      running the script.
    :param type_option: A value from PackageInstallationTypeOption that indicates the type
      of package to be installed. Default to 'prod', which is a production dependency.
    :param version_option: A value from PackageInstallationVersionOption that indicates how
      to match version. Default to None, which uses package manager default.
    """
    args=self._get_add_package_args(
      package,
      type_option=type_option,
      version_option=version_option)
    return self.run_command(args=args, node_paths=node_paths)

  def run_cli(self, cli, args=None, node_paths=None):
    """Returns a command that when executed will run an installed cli via package manager."""
    cli_args = [cli]
    if args:
      cli_args.append('--')
      cli_args.extend(args)
    return self.run_command(args=cli_args, node_paths=node_paths)


class PackageManagerYarnpkg(PackageManager):

  def __init__(self, tool_installation):
    super(PackageManagerYarnpkg, self).__init__(PACKAGE_MANAGER_YARNPKG, tool_installation)

  def _get_run_script_args(self):
    return ['run']

  def _get_installation_args(self, install_optional, production_only, force, frozen_lockfile):
    return_args = ['--non-interactive']
    if not install_optional:
      return_args.append('--ignore-optional')
    if production_only:
      return_args.append('--production=true')
    if force:
      return_args.append('--force')
    if frozen_lockfile:
      return_args.append('--frozen-lockfile')
    return return_args

  def _get_add_package_args(self, package, type_option, version_option):
    return_args = ['add', package]
    package_type_option = {
      PackageInstallationTypeOption.PROD: '',  # Yarn save production is the default.
      PackageInstallationTypeOption.DEV: '--dev',
      PackageInstallationTypeOption.PEER: '--peer',
      PackageInstallationTypeOption.OPTIONAL: '--optional',
      PackageInstallationTypeOption.BUNDLE: None,
      PackageInstallationTypeOption.NO_SAVE: None,
    }.get(type_option)
    if package_type_option is None:
      LOG.warning('{} does not support {} packages, ignored.'.format(self.name, type_option))
    elif package_type_option:  # Skip over '' entries
      return_args.append(package_type_option)
    package_version_option = {
      PackageInstallationVersionOption.EXACT: '--exact',
      PackageInstallationVersionOption.TILDE: '--tilde',
    }.get(version_option)
    if package_version_option is None:
      LOG.warning(
        '{} does not support install with {} version, ignored'.format(self.name, version_option))
    elif package_version_option: # Skip over '' entries
      return_args.append(package_version_option)
    return return_args


class PackageManagerNpm(PackageManager):

  def __init__(self, tool_installation):
    super(PackageManagerNpm, self).__init__(PACKAGE_MANAGER_NPM, tool_installation)

  def _get_run_script_args(self):
    return ['run-script']

  def _get_installation_args(self, install_optional, production_only, force, frozen_lockfile):
    return_args = ['install']
    if not install_optional:
      return_args.append('--no-optional')
    if production_only:
      return_args.append('--production')
    if force:
      return_args.append('--force')
    if frozen_lockfile:
      LOG.warning('{} does not support frozen lockfile option. Ignored.'.format(self.name))
    return return_args

  def _get_add_package_args(self, package, type_option, version_option):
    return_args = ['install', package]
    package_type_option = {
      PackageInstallationTypeOption.PROD: '--save-prod',
      PackageInstallationTypeOption.DEV: '--save-dev',
      PackageInstallationTypeOption.PEER: None,
      PackageInstallationTypeOption.OPTIONAL: '--save-optional',
      PackageInstallationTypeOption.BUNDLE: '--save-bundle',
      PackageInstallationTypeOption.NO_SAVE: '--no-save',
    }.get(type_option)
    if package_type_option is None:
      LOG.warning('{} does not support {} packages, ignored.'.format(self.name, type_option))
    elif package_type_option:  # Skip over '' entries
      return_args.append(package_type_option)
    package_version_option = {
      PackageInstallationVersionOption.EXACT: '--save-exact',
      PackageInstallationVersionOption.TILDE: None,
    }.get(version_option)
    if package_version_option is None:
      LOG.warning(
        '{} does not support install with {} version, ignored.'.format(self.name, version_option))
    elif package_version_option:  # Skip over '' entries
      return_args.append(package_version_option)
    return return_args

  def run_cli(self, cli, args=None, node_paths=None):
    raise RuntimeError('npm does not support run cli directly.  Please use Yarn instead.')
