# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json

from pants.base.exceptions import TaskError
from pants.build_graph.source_mapper import LazySourceMapper
from pants.task.console_task import ConsoleTask


class ListOwners(ConsoleTask):
  """Print targets that own a source file.

      $ pants targets -- path/to/my/source.java
      path/to/my:target1
      another/path:target2
  """

  @classmethod
  def register_options(cls, register):
    super(ListOwners, cls).register_options(register)
    # TODO: consider refactoring out common output format methods into MultiFormatConsoleTask.
    register('--output-format', default='text', choices=['text', 'json'],
             help='Output format of results.')

  @classmethod
  def supports_passthru_args(cls):
    return True

  def console_output(self, targets):
    sources = self.get_passthru_args()
    if not sources:
      raise TaskError('No source was specified')
    lazy_source_mapper = LazySourceMapper(self.context.address_mapper, self.context.build_graph)
    owner_info = {}
    for source in sources:
      owner_info[source] = []
      target_addresses_for_source = lazy_source_mapper.target_addresses_for_source(source)
      for address in target_addresses_for_source:
        owner_info[source].append(address.spec)
    if self.get_options().output_format == 'json':
      yield json.dumps(owner_info, indent=4, separators=(',', ': '))
    else:
      if len(sources) > 1:
        raise TaskError('Too many sources specified for {} output format.'
                        .format(self.get_options().output_format))
      if owner_info.values():
        for address_spec in owner_info.values()[0]:
          yield address_spec
