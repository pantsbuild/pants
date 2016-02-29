# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.bin.goal_runner import OptionsInitializer
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.fs import create_fs_tasks
from pants.engine.exp.graph import create_graph_tasks
from pants.engine.exp.legacy.graph import ExpGraph, create_legacy_graph_tasks
from pants.engine.exp.legacy.parser import LegacyPythonCallbacksParser, TargetAdaptor
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.nodes import Subjects
from pants.engine.exp.parsers import SymbolTable
from pants.engine.exp.scheduler import LocalScheduler
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
    return {alias: TargetAdaptor for alias in cls.aliases().target_types}


def list():
  """Lists all addresses under the current build root."""

  build_root = get_buildroot()
  cmd_line_spec_parser = CmdLineSpecParser(build_root)
  spec_roots = [cmd_line_spec_parser.parse_spec(spec) for spec in sys.argv[1:]]

  subjects = Subjects(debug=True)
  symbol_table_cls = LegacyTable

  # Register "literal" subjects required for these tasks.
  # TODO: Replace with `Subsystems`.
  project_tree_key = subjects.put(
      FileSystemProjectTree(build_root))
  address_mapper_key = subjects.put(
      AddressMapper(symbol_table_cls=symbol_table_cls,
                    parser_cls=LegacyPythonCallbacksParser))

  # Create a Scheduler containing only the graph tasks, with a single installed goal that
  # requests an Address.
  tasks = (
      create_legacy_graph_tasks() +
      create_fs_tasks(project_tree_key) +
      create_graph_tasks(address_mapper_key, symbol_table_cls)
    )
  scheduler = LocalScheduler({}, tasks, subjects, symbol_table_cls)

  # Execute a request for the given specs.
  engine = LocalSerialEngine(scheduler)
  engine.start()
  try:
    graph = ExpGraph(address_mapper=None, scheduler=scheduler, engine=engine)
    for address in graph.inject_specs_closure(spec_roots):
      print(address)
  finally:
    engine.close()
