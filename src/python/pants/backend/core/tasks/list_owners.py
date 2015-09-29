# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.base.exceptions import TaskError
from pants.build_graph.source_mapper import LazySourceMapper


class ListOwners(ConsoleTask):
  """Given a source file, list all targets that own it::

      $ pants targets -- path/to/my/source.java
      path/to/my:target1
      another/path:target2
  """

  @classmethod
  def supports_passthru_args(cls):
    return True

  def console_output(self, targets):
    sources = self.get_passthru_args()
    if not sources:
      raise TaskError('No source was specified')
    elif len(sources) > 1:
      raise TaskError('Too many sources specified.')
    lazy_source_mapper = LazySourceMapper(self.context.address_mapper, self.context.build_graph)
    for source in sources:
      target_addresses_for_source = lazy_source_mapper.target_addresses_for_source(source)
      for address in target_addresses_for_source:
        yield address.spec
