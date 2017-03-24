# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.base.exceptions import TaskError

from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoCheckstyle(GoWorkspaceTask):
  """Checks Go code matches gofmt style."""

  deprecated_options_scope = 'compile.gofmt'
  deprecated_options_scope_removal_version = '1.5.0.dev0'

  @classmethod
  def register_options(cls, register):
    super(GoCheckstyle, cls).register_options(register)
    register('--skip', type=bool, fingerprint=True, help='Skip checkstyle.')

  _GO_SOURCE_EXTENSION = '.go'

  def _is_checked(self, target):
    return target.has_sources(self._GO_SOURCE_EXTENSION) and not target.is_synthetic

  def execute(self):
    if self.get_options().skip:
      return
    targets = self.context.targets(self._is_checked)
    with self.invalidated(targets) as invalidation_check:
      invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]
      sources = self.calculate_sources(invalid_targets)
      if sources:
        args = [os.path.join(self.go_dist.goroot, 'bin', 'gofmt'), '-d'] + list(sources)
        try:
          output = subprocess.check_output(args)
        except subprocess.CalledProcessError as e:
          raise TaskError('{} failed with exit code {}'.format(' '.join(args), e.returncode),
                          exit_code=e.returncode)
        if output:
          self.context.log.error(output)
          raise TaskError('Found style errors. Use `./pants fmt` to fix.')

  def calculate_sources(self, targets):
    sources = set()
    for target in targets:
      sources.update(source for source in target.sources_relative_to_buildroot()
                     if source.endswith(self._GO_SOURCE_EXTENSION))
    return sources
