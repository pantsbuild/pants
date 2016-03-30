# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import sys
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.base.specs import DescendantAddresses
from pants.bin.goal_runner import OptionsInitializer
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.fs import Path, create_fs_tasks
from pants.engine.exp.graph import create_graph_tasks
from pants.engine.exp.legacy.graph import ExpGraph, create_legacy_graph_tasks
from pants.engine.exp.legacy.parser import LegacyPythonCallbacksParser, TargetAdaptor
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.nodes import FilesystemNode
from pants.engine.exp.parser import SymbolTable
from pants.engine.exp.scheduler import LocalScheduler
from pants.engine.exp.storage import Storage
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.subsystem.pants_daemon_launcher import PantsDaemonLauncher
from pants.util.memo import memoized_method


class LegacyTable(SymbolTable):
  @classmethod
  @memoized_method
  def aliases(cls):
    """TODO: This is a nasty escape hatch to pass aliases to LegacyPythonCallbacksParser."""
    _, build_config = OptionsInitializer(OptionsBootstrapper()).setup()
    return build_config.registered_aliases()

  @classmethod
  @memoized_method
  def table(cls):
    return {alias: TargetAdaptor for alias in cls.aliases().target_types}


def setup(options=None):
  if not options:
    options, _ = OptionsInitializer(OptionsBootstrapper()).setup()
  build_root = get_buildroot()
  cmd_line_spec_parser = CmdLineSpecParser(build_root)
  spec_roots = [cmd_line_spec_parser.parse_spec(spec) for spec in options.target_specs]

  storage = Storage.create(debug=False)
  project_tree = FileSystemProjectTree(build_root)
  symbol_table_cls = LegacyTable

  # Register "literal" subjects required for these tasks.
  # TODO: Replace with `Subsystems`.
  address_mapper = AddressMapper(symbol_table_cls=symbol_table_cls,
                                 parser_cls=LegacyPythonCallbacksParser)

  # Create a Scheduler containing graph and filesystem tasks, with no installed goals. The ExpGraph
  # will explicitly request the products it needs.
  tasks = (
    create_legacy_graph_tasks() +
    create_fs_tasks() +
    create_graph_tasks(address_mapper, symbol_table_cls)
  )

  return (
    LocalScheduler(dict(), tasks, storage, project_tree),
    storage,
    options,
    spec_roots,
    symbol_table_cls
  )


def maybe_launch_pantsd(options, scheduler):
  if options.for_global_scope().enable_pantsd is True:
    pantsd_launcher = PantsDaemonLauncher.global_instance()
    pantsd_launcher.set_scheduler(scheduler, (Path, DescendantAddresses), FilesystemNode)
    pantsd_launcher.maybe_launch()


@contextmanager
def setup_graph(*args, **kwargs):
  scheduler, storage, options, spec_roots, symbol_table_cls = setup(*args, **kwargs)

  # Populate the graph for the given request, and print the resulting Addresses.
  engine = LocalSerialEngine(scheduler, storage)
  engine.start()
  try:
    graph = ExpGraph(scheduler, engine, symbol_table_cls)
    addresses = tuple(graph.inject_specs_closure(spec_roots))
    yield graph, addresses, scheduler
    maybe_launch_pantsd(options, scheduler)
  finally:
    print('Cache stats: {}'.format(engine._cache.get_stats()), file=sys.stderr)
    engine.close()


@contextmanager
def _open_graph():
  with setup_graph() as (graph, addresses, _):
    yield graph, addresses


@contextmanager
def _open_scheduler():
  with setup_graph() as (_, _, scheduler):
    yield scheduler


def dependencies():
  """Lists the transitive dependencies of targets under the current build root."""
  with _open_graph() as (graph, addresses):
    for address in addresses:
      print(address)


def filemap():
  """Lists the transitive dependencies of targets under the current build root."""
  with _open_graph() as (graph, addresses):
    for address in addresses:
      target = graph.get_target(address)
      for source in target.sources_relative_to_buildroot():
        print('{} {}'.format(source, target.address.spec))


def fsnodes():
  """Prints out all of the FilesystemNodes in the Scheduler for debugging purposes."""
  with _open_scheduler() as scheduler:
    for node in scheduler.product_graph.completed_nodes():
      if type(node) is FilesystemNode:
        print(node)
