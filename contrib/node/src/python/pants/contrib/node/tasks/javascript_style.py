# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.option.custom_types import file_option
from pants.util.contextutil import pushd
from pants.util.memo import memoized_method

from pants.contrib.node.targets.node_package import NodePackage
from pants.contrib.node.tasks.node_paths import NodePaths
from pants.contrib.node.tasks.node_task import NodeTask


class JavascriptStyle(NodeTask):
  """ Check javascript source files to ensure they follow the style guidelines.

  :API: public
  """

  _JS_SOURCE_EXTENSION = '.js'
  _JSX_SOURCE_EXTENSION = '.jsx'
  INSTALL_JAVASCRIPTSTYLE_TARGET_NAME = 'synthetic-install-javascriptstyle-module'

  def __init__(self, *args, **kwargs):
    super(JavascriptStyle, self).__init__(*args, **kwargs)

  @classmethod
  def register_options(cls, register):
    super(JavascriptStyle, cls).register_options(register)
    register('--skip', type=bool, fingerprint=True, help='Skip javascriptstyle.')
    register('--fail-slow', type=bool,
             help='Check all targets and present the full list of errors.')
    register('--javascriptstyle-dir', advanced=True, fingerprint=True,
             help='Package directory for lint tool.')

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

  @memoized_method
  def _install_javascriptstyle(self):
    javascriptstyle_dir = self.get_options().javascriptstyle_dir
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

  def _run_javascriptstyle(self, target, javascriptstyle_bin_path, files, fix=False):
    args = [javascriptstyle_bin_path]
    if fix:
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
    if self.get_options().skip:
      self.context.log.info('Skipping javascript style check.')
      return

    targets = self.get_lintable_node_targets(self.context.targets())
    if not targets:
      return
    failed_targets = []

    javascriptstyle_bin_path = self._install_javascriptstyle()
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


class JavascriptStyleFmt(JavascriptStyle):
  """Check and fix source files to ensure they follow the style guidelines.

  :API: public
  """

  def _run_javascriptstyle(self, target, javascriptstyle_bin_path, files, fix=True):
    return super(JavascriptStyleFmt, self)._run_javascriptstyle(target,
                                                                javascriptstyle_bin_path,
                                                                files,
                                                                fix=fix)
