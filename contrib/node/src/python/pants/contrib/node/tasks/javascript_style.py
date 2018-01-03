# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from pants.contrib.node.subsystems.eslint_distribution import ESLintDistribution
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.util.contextutil import pushd
from pants.util.memo import (memoized_method, memoized_property)

from pants.contrib.node.targets.node_module import NodeModule
from pants.contrib.node.tasks.node_task import NodeTask


class JavascriptStyle(NodeTask):
  """ Check javascript source files to ensure they follow the style guidelines.

  :API: public
  """

  _JS_SOURCE_EXTENSION = '.js'
  _JSX_SOURCE_EXTENSION = '.jsx'
  INSTALL_JAVASCRIPTSTYLE_TARGET_NAME = 'synthetic-install-javascriptstyle-module'

  @classmethod
  def subsystem_dependencies(cls):
    return super(JavascriptStyle, cls).subsystem_dependencies() + (ESLintDistribution.Factory,)

  @memoized_property
  def eslint_distribution(self):
    """A bootstrapped eslint distribution for use by javascript style checking."""
    return ESLintDistribution.Factory.global_instance().create()

  def __init__(self, *args, **kwargs):
    super(JavascriptStyle, self).__init__(*args, **kwargs)

  @classmethod
  def register_options(cls, register):
    super(JavascriptStyle, cls).register_options(register)
    register('--skip', type=bool, fingerprint=True, help='Skip javascriptstyle.')
    register('--fail-slow', type=bool,
             help='Check all targets and present the full list of errors.')
    register('--color', type=bool, default=True, help='Enable or disable color.')
    register('--transitive', type=bool, default=True,
             help='True to run the tool transitively on targets in the context, false to run '
                  'for only roots specified on the commandline.')

  def get_lintable_node_targets(self, targets):
    return filter(
      lambda target: isinstance(target, NodeModule)
                     and (target.has_sources(self._JS_SOURCE_EXTENSION)
                          or target.has_sources(self._JSX_SOURCE_EXTENSION))
                     and (not target.is_synthetic),
      targets)

  def get_javascript_sources(self, target):
    sources = set()
    sources.update(os.path.join(get_buildroot(), source) for source in target.sources_relative_to_buildroot()
                   if (source.endswith(self._JS_SOURCE_EXTENSION) or
                       source.endswith(self._JSX_SOURCE_EXTENSION)))
    return sources

  def _is_javascriptstyle_dir_valid(self, javascriptstyle_dir):
    dir_exists = os.path.isdir(javascriptstyle_dir)
    if not dir_exists:
      raise TaskError(
        'javascriptstyle package does not exist: {}.'.format(javascriptstyle_dir))
      return False
    else:
      lock_file = os.path.join(javascriptstyle_dir, 'yarn.lock')
      package_json = os.path.join(javascriptstyle_dir, 'package.json')
      files_exist = os.path.isfile(lock_file) and os.path.isfile(package_json)
      if not files_exist:
        raise TaskError(
          'javascriptstyle cannot be installed because yarn.lock '
          'or package.json does not exist.')
        return False
    return True


  @memoized_method
  def _bootstrap_default_eslinter(self, bootstrap_dir):
    with pushd(bootstrap_dir):
      result, yarn_add_command = self.execute_yarnpkg(
        args=['add', 'eslint'],
        workunit_name=self.INSTALL_JAVASCRIPTSTYLE_TARGET_NAME,
        workunit_labels=[WorkUnitLabel.PREP])
      if result != 0:
        raise TaskError('Failed to install eslint\n'
                        '\t{} failed with exit code {}'.format(yarn_add_command, result))
    return bootstrap_dir

  @memoized_method
  def _install_eslint(self, bootstrap_dir):
    """Install the ESLint distribution.

    :rtype: string
    """
    with pushd(bootstrap_dir):
      result, yarn_install_command = self.execute_yarnpkg(
        args=['install'],
        workunit_name=self.INSTALL_JAVASCRIPTSTYLE_TARGET_NAME,
        workunit_labels=[WorkUnitLabel.PREP])
      if result != 0:
        raise TaskError('Failed to install ESLint\n'
                        '\t{} failed with exit code {}'.format(yarn_install_command, result))

    self.context.log.debug('Successfully installed ESLint to {}'.format(bootstrap_dir))
    return bootstrap_dir

  def _get_target_ignore_patterns(self, target):
    ignore_path = next((source for source in target.sources_relative_to_buildroot()
                        if os.path.basename(source) == target.style_ignore_path), None)
    ignore_patterns = []
    if ignore_path:
      root_dir = os.path.join('**', os.path.dirname(ignore_path))
      with open(ignore_path) as f:
        ignore_patterns = f.readlines()
        ignore_patterns = [os.path.join(root_dir, p.strip()) for p in ignore_patterns]
    return ignore_patterns

  def _run_javascriptstyle(self, target, bootstrap_dir, files, config=None, ignore_path=None,
                           fix=False, other_args=None):
    args = ['eslint', '--']
    if config:
      args.extend(['--config', config])
    else:
      args.extend(['--no-eslintrc'])
    if ignore_path:
      args.extend(['--ignore-path', ignore_path])
    if fix:
      self.context.log.info('Autoformatting is enabled for javascriptstyle.')
      args.extend(['--fix'])
    if self.get_options().color:
      args.extend(['--color'])
    ignore_patterns = self._get_target_ignore_patterns(target)
    if ignore_patterns:
      # Wrap ignore-patterns in quotes to avoid conflict with shell glob pattern
      args.extend([arg for ignore_args in ignore_patterns
                   for arg in ['--ignore-pattern', '"{}"'.format(ignore_args)]])
    if other_args:
      args.extend(other_args)
    args.extend(files)
    with pushd(bootstrap_dir):
      result, yarn_run_command = self.execute_yarnpkg(
        args=args,
        workunit_name=target.address.reference(),
        workunit_labels=[WorkUnitLabel.PREP])
      self.context.log.debug('Javascript style command: {}'.format(yarn_run_command))
    return (result, yarn_run_command)

  def execute(self):
    if self.get_options().skip:
      self.context.log.info('Skipping javascript style check.')
      return

    all_targets = self.context.targets() if self.get_options().transitive else self.context.target_roots
    targets = self.get_lintable_node_targets(all_targets)
    if not targets:
      return
    failed_targets = []

    bootstrap_dir, is_preconfigured = self.eslint_distribution.fetch_supportdir()

    if not is_preconfigured:
      self.context.log.debug('ESLint is not pre-configured, bootstrapping with defaults.')
      self._bootstrap_default_eslinter(bootstrap_dir)
    else:
      self._install_eslint(bootstrap_dir)
    for target in targets:
      files = self.get_javascript_sources(target)
      if files:
        result_code, command = self._run_javascriptstyle(target,
                                                         bootstrap_dir,
                                                         files,
                                                         config=self.eslint_distribution.eslint_config,
                                                         ignore_path=self.eslint_distribution._eslint_ignore)
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


class JavascriptStyleFmt(JavascriptStyle):
  """Check and fix source files to ensure they follow the style guidelines.

  :API: public
  """

  def _run_javascriptstyle(self, target, javascriptstyle_bin_path, files, fix=True):
    return super(JavascriptStyleFmt, self)._run_javascriptstyle(target,
                                                                javascriptstyle_bin_path,
                                                                files,
                                                                config=self.eslint_distribution.eslint_config,
                                                                ignore_path=self.eslint_distribution._eslint_ignore,
                                                                fix=fix)
