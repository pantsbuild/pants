# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.source_root import SourceRoot
from pants.backend.core.tasks.console_task import ConsoleTask


class ListRoots(ConsoleTask):
  """List the registered source roots of the repo."""

  def console_output(self, targets):
    for src_root, targets in SourceRoot.all_roots().items():
      all_targets = ','.join(sorted([tgt.__name__ for tgt in targets]))
      yield '%s: %s' % (src_root, all_targets or '*')
