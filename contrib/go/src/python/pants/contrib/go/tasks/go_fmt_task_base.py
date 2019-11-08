# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import subprocess
from contextlib import contextmanager

from pants.base.exceptions import TaskError

from pants.contrib.go.targets.go_local_source import GoLocalSource
from pants.contrib.go.tasks.go_workspace_task import GoWorkspaceTask


class GoFmtTaskBase(GoWorkspaceTask):
  """Base class for tasks that run gofmt."""

  @classmethod
  def is_checked(cls, target):
    return isinstance(target, GoLocalSource) and not target.is_synthetic

  @classmethod
  def calculate_sources(cls, targets):
    sources = set()
    for target in targets:
      sources.update(source for source in target.sources_relative_to_buildroot()
                     if GoLocalSource.is_go_source(source))
    return sources

  @contextmanager
  def go_fmt_invalid_targets(self, flags):
    targets = self.get_targets(self.is_checked)
    with self.invalidated(targets) as invalidation_check:
      invalid_targets = [vt.target for vt in invalidation_check.invalid_vts]
      sources = self.calculate_sources(invalid_targets)
      if sources:
        args = [os.path.join(self.go_dist.goroot, 'bin', 'gofmt')] + flags + list(sources)
        try:
          output = subprocess.check_output(args).decode()
        except subprocess.CalledProcessError as e:
          raise TaskError('{} failed with exit code {}'.format(' '.join(args), e.returncode),
                          exit_code=e.returncode)
        yield output
      else:
        yield None
