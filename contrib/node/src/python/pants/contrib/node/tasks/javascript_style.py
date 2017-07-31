# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.exceptions import TaskError
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.option.custom_types import file_option
from pants.util.contextutil import pushd
from pants.base.build_environment import get_buildroot

from pants.contrib.node.targets.node_package import NodePackage
from pants.contrib.node.tasks.node_task import NodeTask
from pants.contrib.node.tasks.node_paths import NodePaths


class JavascriptStyle(NodeTask):
  """ Check javascript source files to ensure they follow the style guidelines.

  :API: public
  """

  _JS_SOURCE_EXTENSION = '.js'
  _JSX_SOURCE_EXTENSION = '.jsx'

  def __init__(self, *args, **kwargs):
    super(JavascriptStyle, self).__init__(*args, **kwargs)

  @classmethod
  def register_options(cls, register):
    super(JavascriptStyle, cls).register_options(register)
    register('--cmd', advanced=True, default='eslint', fingerprint=True,
             help='Run this command to start style checker.')
    register('--cmd-args', advanced=True, type=list, default=[], fingerprint=True,
             help='Passthrough command line args.')
    register('--package', advanced=True, default='eslint', fingerprint=True, help='Linter tool')
    register('--skip', type=bool, fingerprint=True, help='Skip javascriptstyle.')
    register('--config', type=file_option, advanced=True, fingerprint=True,
             help='Path to javascriptstyle config file.')
    register('--linter-plugins', advanced=True, type=list, default=[], fingerprint=True,
             help='Add these plugins to extend linter.')

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

  def _install_packages(self, target, packages):
    """Install packages related to javascript style checker."""
    for package in packages:
      self.context.log.debug('Installing package %s.'% package)
      result, yarn_add_command = self.execute_yarnpkg(
        args=['add', package],
        workunit_name=target.address.reference(),
        workunit_labels=[WorkUnitLabel.PREP])
      if result != 0:
        raise TaskError('Failed to install package: {}\n'
                        '\t{} failed with exit code {}'.format(package, yarn_add_command, result))

  def _run_lint_tool(self, target, files):
    command = self.get_options().cmd
    command_args = self.get_options().cmd_args
    global_config = self.get_options().config
    config = target.payload.get_field('lint_config').value
    # If no config file is specified use default config.
    if not config:
      config = global_config
    self.context.log.info('Config: %s' % config)
    args = ['run', command, '--', '--config', config, files]
    args.extend(command_args)
    result, yarn_run_command = self.execute_yarnpkg(
      args=args,
      workunit_name=target.address.reference(),
      workunit_labels=[WorkUnitLabel.PREP])
    if result != 0:
      raise TaskError('Linting failed: \n'
                      '{} failed with exit code {}'.format(yarn_run_command, result))

  def execute(self):
    if self.get_options().skip:
      self.context.log.info('Skipping javascript style check.')
      return

    targets = self.get_lintable_node_targets(self.context.targets())
    if not targets:
      return
    
    for target in targets:
      packages = [self.get_options().package]
      sources = self.get_javascript_sources(target)
      if sources:
        files = ' '.join(sources)
        node_paths = self.context.products.get_data(NodePaths)
        node_path = node_paths.node_path(target) 
        with pushd(node_path):
          packages.extend(self.get_options().linter_plugins)
          self._install_packages(target, packages)
          self._run_lint_tool(target, files)
    return