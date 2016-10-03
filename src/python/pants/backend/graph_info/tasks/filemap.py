# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.console_task import ConsoleTask


class Filemap(ConsoleTask):
  """Print a mapping from source file to the target that owns the source file."""

  def console_output(self, _):
    visited = set()
    for target in self.determine_target_roots('filemap'):
      if target not in visited:
        visited.add(target)
        for rel_source in target.sources_relative_to_buildroot():
          yield '{} {}'.format(rel_source, target.address.spec)
