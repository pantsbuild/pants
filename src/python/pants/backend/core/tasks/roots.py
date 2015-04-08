# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.source_root import SourceRoot


class ListRoots(ConsoleTask):
  """List the registered source roots of the repo."""

  def console_output(self, targets):
    for src_root, targets in SourceRoot.all_roots().items():
      all_targets = ','.join(sorted([tgt.__name__ for tgt in targets]))
      yield '{}: {}'.format(src_root, all_targets or '*')
