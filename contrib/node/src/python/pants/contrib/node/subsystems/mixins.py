# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.contrib.node.subsystems.command import command_gen


PACKAGE_MANAGER_NPM = 'npm'
PACKAGE_MANAGER_YARNPKG = 'yarnpkg'


class PackageManagerMixin(object):
  """Defines node package manager functionalities."""

  def _get_installation_args(self, install_optional):
    """Returns command line args for installing package.

    :param install_optional: True to request install optional dependencies.
    :rtype: list of strings
    """
    raise NotImplementedError

  def _get_run_script_args(self):
    """Returns command line args to run a package.json script.

    :rtype: list of strings
    """
    raise NotImplementedError

  def install_packages(self, install_optional=False, node_paths=None):
    """Returns a command that when executed will install node package.

    :param install_optional: True to install optional dependencies.
    :param node_paths: A list of path that should be included in $PATH when
      running installation.
    """
    return command_gen(
      self,
      args=self._get_installation_args(install_optional=install_optional),
      node_paths=node_paths
    )

  def run_script(self, script_name, script_args=None, node_paths=None):
    """Returns a command to execute a package.json script.

    :param script_name: Name of the script to name.  Note that script name 'test'
      can be used to run node tests.
    :param script_args: Args to be passed to package.json script.
    :param node_paths: A list of path that should be included in $PATH when
      running the script.
    """
    package_manager_args = self._get_run_script_args()
    package_manager_args.append(script_name)
    if script_args:
      package_manager_args.append('--')
      package_manager_args.extend(script_args)
    return command_gen(
      self,
      args=package_manager_args,
      node_paths=node_paths
    )
