# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import itertools

from pants.backend.jvm.targets.jvm_binary import JvmApp
from pants.backend.core.tasks.console_task import ConsoleTask

# XXX(pl): JVM hairball violator
class FileDeps(ConsoleTask):
  def console_output(self, targets):
    files = set()
    for target in targets:
      if target.has_sources():
        files.update(target.expand_files(recursive=False))
      if isinstance(target, JvmApp):
        files.update(itertools.chain(*[bundle.filemap.keys() for bundle in target.bundles]))
    return files
