# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.specs import DescendantAddresses
from pants.bin.goal_runner import OptionsInitializer
from pants.build_graph.address import Address
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.fs import create_fs_tasks
from pants.engine.exp.graph import create_graph_tasks
from pants.engine.exp.legacy.parsers import LegacyPythonCallbacksParser
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.nodes import Return, State, Throw
from pants.engine.exp.parsers import SymbolTable
from pants.engine.exp.scheduler import BuildRequest, LocalScheduler
from pants.engine.exp.targets import Target
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.memo import memoized_method


class LegacyTable(SymbolTable):

  @classmethod
  @memoized_method
  def aliases(cls):
    """TODO: This is a nasty escape hatch to pass aliases to LegacyPythonCallbacksParser."""
    options, build_config = OptionsInitializer(OptionsBootstrapper()).setup()
    return build_config.registered_aliases()

  @classmethod
  @memoized_method
  def table(cls):
    return {alias: Target for alias in cls.aliases().target_types}


def list():
  """Lists all addresses under the current build root."""

  build_root = get_buildroot()
  symbol_table_cls = LegacyTable
  address_mapper = AddressMapper(symbol_table_cls=symbol_table_cls,
                                 parser_cls=LegacyPythonCallbacksParser)

  # Create a Scheduler containing only the graph tasks, with a single installed goal that
  # requests an Address.
  goal = 'list'
  tasks = create_fs_tasks(build_root) + create_graph_tasks(address_mapper, symbol_table_cls)
  scheduler = LocalScheduler({goal: Address}, symbol_table_cls, tasks)

  # Execute a request for the root.
  build_request = BuildRequest(goals=[goal], subjects=[DescendantAddresses('')])
  result = LocalSerialEngine(scheduler).execute(build_request)
  if result.error:
    raise result.error

  # Render the output.
  for state in result.root_products.values():
    if type(state) is Throw:
      raise state.exc
    elif type(state) is not Return:
      State.raise_unrecognized(dep_state)
    for address in state.value:
      print(address)
