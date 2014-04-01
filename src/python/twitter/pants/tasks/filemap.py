# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.target import Target
from pants.tasks.console_task import ConsoleTask


class Filemap(ConsoleTask):
  """Outputs a mapping from source file to the target that owns the source file."""

  def console_output(self, _):
    visited = set()
    for target in self._find_targets():
      if target not in visited:
        visited.add(target)
        if hasattr(target, 'sources') and target.sources is not None:
          for sourcefile in target.sources:
            path = os.path.join(target.target_base, sourcefile)
            yield '%s %s' % (path, target.address)

  def _find_targets(self):
    if len(self.context.target_roots) > 0:
      for target in self.context.target_roots:
        yield target
    else:
      for buildfile in BuildFile.scan_buildfiles(get_buildroot()):
        target_addresses = Target.get_all_addresses(buildfile)
        for target_address in target_addresses:
          yield Target.get(target_address)
