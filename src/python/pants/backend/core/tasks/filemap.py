# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.backend.core.tasks.console_task import ConsoleTask


class Filemap(ConsoleTask):
  """Outputs a mapping from source file to the target that owns the source file."""

  def console_output(self, _):
    visited = set()
    for target in self._find_targets():
      if target not in visited:
        visited.add(target)
        if hasattr(target.payload, 'sources') and target.payload.sources is not None:
          for sourcefile in target.payload.sources:
            path = os.path.normpath(os.path.join(target.payload.sources_rel_path,
                                                 sourcefile))
            yield '%s %s' % (path, target.address.spec)

  def _find_targets(self):
    if len(self.context.target_roots) > 0:
      return self.context.target_roots
    else:
      return self.context.build_file_parser.scan().targets()
