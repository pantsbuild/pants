# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.task.console_task import ConsoleTask


class ListRoots(ConsoleTask):
  """List the registered source roots of the repo."""

  def console_output(self, targets):
    for src_root in self.context.source_roots.all_roots():
      all_langs = ','.join(sorted(src_root.langs))
      yield '{}: {}'.format(src_root.path, all_langs or '*')
