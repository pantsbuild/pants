# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.deprecated import deprecated
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnitLabel
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.contextutil import pushd
from pants.util.memo import memoized_method

from pants.contrib.node.targets.node_package import NodePackage
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
    register('--javascriptstyle-dir', advanced=True, fingerprint=True,
             help='Package directory for lint tool.')

  @property
  def fix(self):
    """Whether to fix discovered style errors."""
    raise NotImplementedError()

  def get_lintable_node_targets(self, targets):
    return filter(
      lambda target: isinstance(target, NodePackage)
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
  def _install_javascriptstyle(self, javascriptstyle_dir):
    with pushd(javascriptstyle_dir):
      result, yarn_add_command = self.execute_yarnpkg(
        args=['install'],
        workunit_name=self.INSTALL_JAVASCRIPTSTYLE_TARGET_NAME,
        workunit_labels=[WorkUnitLabel.PREP])
      if result != 0:
        raise TaskError('Failed to install javascriptstyle\n'
                        '\t{} failed with exit code {}'.format(yarn_add_command, result))
    javascriptstyle_bin_path = os.path.join(javascriptstyle_dir, 'bin', 'cli.js')
    return javascriptstyle_bin_path

  def _run_javascriptstyle(self, target, javascriptstyle_bin_path, files):
    args = [javascriptstyle_bin_path]
    if self.fix:
      self.context.log.info('Autoformatting is enabled for javascriptstyle.')
      args.extend(['--fix'])
    args.extend(files)
    result, node_run_command = self.execute_node(
      args=args,
      workunit_name=target.address.reference(),
      workunit_labels=[WorkUnitLabel.PREP])
    if result != 0 and not self.get_options().fail_slow:
      raise TaskError('Javascript linting failed: \n'
                      '{} failed with exit code {}'.format(node_run_command, result))
    return result

  def execute(self):
    targets = self.get_lintable_node_targets(self.get_targets())
    if not targets:
      return
    failed_targets = []

    # TODO: If javascriptstyle is not configured, pants should use a default installation.
    # Some concerns and thoughts regarding the current javascriptstyle implementation:
    # 1.) The javascriptstyle package itself is designed to be mutable. That is problematic
    #     as there can be many changes in the same package version across multiple installations.
    #     Pushing updates to the original package will feel more like a major revision.
    # 2.) The decision was made to ensure deterministic installation using yarn.lock file. The lock
    #     file is produced after an installation. And all eslint plugins need to be final and
    #     explicit during installation time.
    # 3.) We can potentially solve this using a caching solution for yarn.lock/package.json files.
    #     That is, javascriptstyle package should only include base eslint + rules and all plugins
    #     and additional rules should be configured through pants.ini.
    javascriptstyle_dir = self.get_options().javascriptstyle_dir
    if not (javascriptstyle_dir and self._is_javascriptstyle_dir_valid(javascriptstyle_dir)):
      self.context.log.warn('javascriptstyle is not configured, skipping javascript style check.')
      self.context.log.warn(
        'See https://github.com/pantsbuild/pants/tree/master/build-support/'
        'javascriptstyle/README.md')
      return

    javascriptstyle_bin_path = self._install_javascriptstyle(javascriptstyle_dir)
    for target in targets:
      files = self.get_javascript_sources(target)
      if files:
        result_code = self._run_javascriptstyle(target, javascriptstyle_bin_path, files)
        if result_code != 0:
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


# Deprecated old name for class.
class JavascriptStyle(JavascriptStyleLint):
  @deprecated('1.7.0.dev0', 'Replace with JavascriptStyleLint.')
  def __init__(self, *args, **kwargs):
    super(JavascriptStyle, self).__init__(*args, **kwargs)
