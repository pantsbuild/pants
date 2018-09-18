# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import open

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.contextutil import pushd
from pants.util.memo import memoized_method

from pants.contrib.node.subsystems.package_managers import (PACKAGE_MANAGER_YARNPKG,
                                                            PackageInstallationVersionOption)
from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.tasks.node_task import NodeTask


class JavascriptStyleBase(NodeTask):
  """ Check javascript source files to ensure they follow the style guidelines.

  :API: public
  """

  _JS_SOURCE_EXTENSION = '.js'
  _JSX_SOURCE_EXTENSION = '.jsx'
  INSTALL_JAVASCRIPTSTYLE_TARGET_NAME = 'synthetic-install-javascriptstyle-module'

  @classmethod
  def register_options(cls, register):
    super(JavascriptStyleBase, cls).register_options(register)
    register('--fail-slow', type=bool,
             help='Check all targets and present the full list of errors.')
    register('--color', type=bool, default=True, help='Enable or disable color.')

  @property
  def fix(self):
    """Whether to fix discovered style errors."""
    raise NotImplementedError()

  def get_lintable_node_targets(self, targets):
    return [target for target in targets if isinstance(target, NodeModule)
                     and (target.has_sources(self._JS_SOURCE_EXTENSION)
                          or target.has_sources(self._JSX_SOURCE_EXTENSION))
                     and (not target.is_synthetic)]

  def get_javascript_sources(self, target):
    sources = set()
    sources.update(os.path.join(get_buildroot(), source) for source in target.sources_relative_to_buildroot()
                   if (source.endswith(self._JS_SOURCE_EXTENSION) or
                       source.endswith(self._JSX_SOURCE_EXTENSION)))
    return sources

  @staticmethod
  def _is_javascriptstyle_dir_valid(javascriptstyle_dir):
    dir_exists = os.path.isdir(javascriptstyle_dir)
    if not dir_exists:
      raise TaskError(
        'javascriptstyle package does not exist: {}.'.format(javascriptstyle_dir))
    else:
      lock_file = os.path.join(javascriptstyle_dir, 'yarn.lock')
      package_json = os.path.join(javascriptstyle_dir, 'package.json')
      files_exist = os.path.isfile(lock_file) and os.path.isfile(package_json)
      if not files_exist:
        raise TaskError(
          'javascriptstyle cannot be installed because yarn.lock '
          'or package.json does not exist.')
    return True

  @memoized_method
  def _bootstrap_eslinter(self, bootstrap_dir):
    with pushd(bootstrap_dir):
      eslint_version = self.node_distribution.eslint_version
      eslint = 'eslint@{}'.format(eslint_version)
      self.context.log.debug('Installing {}...'.format(eslint))
      result, add_command = self.add_package(
        package=eslint,
        package_manager=self.node_distribution.get_package_manager(package_manager=PACKAGE_MANAGER_YARNPKG),
        version_option=PackageInstallationVersionOption.EXACT,
        workunit_name=self.INSTALL_JAVASCRIPTSTYLE_TARGET_NAME,
        workunit_labels=[WorkUnitLabel.PREP])
      if result != 0:
        raise TaskError('Failed to install eslint\n'
                        '\t{} failed with exit code {}'.format(add_command, result))
    return bootstrap_dir

  @memoized_method
  def _install_eslint(self, bootstrap_dir):
    """Install the ESLint distribution.

    :rtype: string
    """
    with pushd(bootstrap_dir):
      result, install_command = self.install_module(
        package_manager=self.node_distribution.get_package_manager(package_manager=PACKAGE_MANAGER_YARNPKG),
        workunit_name=self.INSTALL_JAVASCRIPTSTYLE_TARGET_NAME,
        workunit_labels=[WorkUnitLabel.PREP])
      if result != 0:
        raise TaskError('Failed to install ESLint\n'
                        '\t{} failed with exit code {}'.format(install_command, result))

    self.context.log.debug('Successfully installed ESLint to {}'.format(bootstrap_dir))
    return bootstrap_dir

  def _get_target_ignore_patterns(self, target):
    for source in target.sources_relative_to_buildroot():
      if os.path.basename(source) == target.style_ignore_path:
        root_dir = os.path.join('**', os.path.dirname(source))
        with open(source, 'r') as f:
          return [os.path.join(root_dir, p.strip()) for p in f]

  def _run_javascriptstyle(self, target, bootstrap_dir, files, config=None, ignore_path=None,
                           other_args=None):
    args = []
    if config:
      args.extend(['--config', config])
    else:
      args.extend(['--no-eslintrc'])
    if ignore_path:
      args.extend(['--ignore-path', ignore_path])
    if self.fix:
      self.context.log.info('Autoformatting is enabled for javascriptstyle.')
      args.extend(['--fix'])
    if self.get_options().color:
      args.extend(['--color'])
    ignore_patterns = self._get_target_ignore_patterns(target)
    if ignore_patterns:
      # Wrap ignore-patterns in quotes to avoid conflict with shell glob pattern
      args.extend([arg for ignore_args in ignore_patterns
                   for arg in ['--ignore-pattern', '{}'.format(ignore_args)]])
    if other_args:
      args.extend(other_args)
    args.extend(files)
    with pushd(bootstrap_dir):
      return self.run_cli('eslint', args=args)

  def execute(self):
    targets = self.get_lintable_node_targets(self.get_targets())
    if not targets:
      return
    failed_targets = []
    bootstrap_dir, is_preconfigured = self.node_distribution.eslint_supportdir(self.workdir)
    if not is_preconfigured:
      self.context.log.debug('ESLint is not pre-configured, bootstrapping with defaults.')
      self._bootstrap_eslinter(bootstrap_dir)
    else:
      self._install_eslint(bootstrap_dir)
    for target in targets:
      files = self.get_javascript_sources(target)
      if files:
        result_code, command = self._run_javascriptstyle(target,
                                                         bootstrap_dir,
                                                         files,
                                                         config=self.node_distribution.eslint_config,
                                                         ignore_path=self.node_distribution.eslint_ignore)
        if result_code != 0:
          if self.get_options().fail_slow:
            raise TaskError('Javascript style failed: \n'
                            '{} failed with exit code {}'.format(command, result_code))
          else:
            failed_targets.append(target)

    if failed_targets:
      msg = 'Failed when evaluating {} targets:\n  {}'.format(
          len(failed_targets),
          '\n  '.join(t.address.spec for t in failed_targets))
      raise TaskError(msg)
    return


class JavascriptStyleLint(LintTaskMixin, JavascriptStyleBase):
  """Check source files to ensure they follow the style guidelines.

  :API: public
  """
  fix = False


class JavascriptStyleFmt(FmtTaskMixin, JavascriptStyleBase):
  """Check and fix source files to ensure they follow the style guidelines.

  :API: public
  """
  fix = True
