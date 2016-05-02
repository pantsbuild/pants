# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.bin.options_initializer import OptionsInitializer
from pants.engine.exp.engine import LocalSerialEngine
from pants.engine.exp.fs import create_fs_tasks
from pants.engine.exp.graph import create_graph_tasks
from pants.engine.exp.legacy.graph import ExpGraph, create_legacy_graph_tasks
from pants.engine.exp.legacy.parser import LegacyPythonCallbacksParser, TargetAdaptor
from pants.engine.exp.mapper import AddressMapper
from pants.engine.exp.parser import SymbolTable
from pants.engine.exp.scheduler import LocalScheduler
from pants.engine.exp.storage import Storage
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.memo import memoized_method


logger = logging.getLogger(__name__)


# N.B. This should be top-level in the module for pickleability - don't nest it.
class LegacySymbolTable(SymbolTable):
  """A v1 SymbolTable facade for use with the v2 engine."""

  @classmethod
  @memoized_method
  def aliases(cls):
    """TODO: This is a nasty escape hatch to pass aliases to LegacyPythonCallbacksParser."""
    _, build_config = OptionsInitializer(OptionsBootstrapper(), init_logging=False).setup()
    return build_config.registered_aliases()

  @classmethod
  @memoized_method
  def table(cls):
    return {alias: TargetAdaptor for alias in cls.aliases().target_types}


class EngineInitializer(object):
  """Constructs the components necessary to run the v2 engine with v1 BuildGraph compatibility."""

  @staticmethod
  def parse_commandline_to_spec_roots(options=None, args=None, build_root=None):
    if not options:
      options, _ = OptionsInitializer(OptionsBootstrapper(args=args), init_logging=False).setup()
    cmd_line_spec_parser = CmdLineSpecParser(build_root or get_buildroot())
    spec_roots = [cmd_line_spec_parser.parse_spec(spec) for spec in options.target_specs]
    return spec_roots

  @staticmethod
  def _setup_scheduler(build_root):
    storage = Storage.create(debug=False)
    # Ignore any dotfile below build_root except `.` itself
    project_tree = FileSystemProjectTree(build_root, ['.*'])
    symbol_table_cls = LegacySymbolTable

    # Register "literal" subjects required for these tasks.
    # TODO: Replace with `Subsystems`.
    address_mapper = AddressMapper(symbol_table_cls=symbol_table_cls,
                                   parser_cls=LegacyPythonCallbacksParser)

    # Create a Scheduler containing graph and filesystem tasks, with no installed goals. The
    # ExpGraph will explicitly request the products it needs.
    tasks = (
      create_legacy_graph_tasks() +
      create_fs_tasks() +
      create_graph_tasks(address_mapper, symbol_table_cls)
    )

    return (
      LocalScheduler(dict(), tasks, storage, project_tree),
      storage,
      symbol_table_cls
    )

  @classmethod
  def setup_legacy_graph(cls):
    build_root = get_buildroot()
    scheduler, storage, symbol_table_cls = cls._setup_scheduler(build_root)
    engine = LocalSerialEngine(scheduler, storage)
    return (scheduler, engine, symbol_table_cls, ExpGraph)

  @classmethod
  @contextmanager
  def open_legacy_graph(cls, options=None):
    """A context manager that yields a usable, legacy ExpGraph by way of the v2 scheduler.

    This is used primarily for testing and non-daemon runs.
    """
    spec_roots = cls.parse_commandline_to_spec_roots(options=options)
    scheduler, engine, symbol_table_cls, build_graph_cls = cls.setup_legacy_graph()

    engine.start()
    try:
      graph = build_graph_cls(scheduler, engine, symbol_table_cls)
      addresses = tuple(graph.inject_specs_closure(spec_roots))
      yield graph, addresses, scheduler
    finally:
      logger.debug('engine cache stats: {}'.format(engine._cache.get_stats()))
      engine.close()
