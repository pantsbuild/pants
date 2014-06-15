# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os

from pants.base.build_environment import get_buildroot
from pants.base.build_file import BuildFile
from pants.base.target import Target
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
            yield '%s %s' % (path, target.address.build_file_spec)

  def _find_targets(self):
    if len(self.context.target_roots) > 0:
      for target in self.context.target_roots:
        yield target
    else:
      build_file_parser = self.context.build_file_parser
      build_graph = self.context.build_graph
      for build_file in BuildFile.scan_buildfiles(get_buildroot()):
        build_file_parser.parse_build_file(build_file)
        for address in build_file_parser.addresses_by_build_file[build_file]:
          build_file_parser.inject_spec_closure_into_build_graph(address.spec, build_graph)
      for target in build_graph._target_by_address.values():
        yield target
