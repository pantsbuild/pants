# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from collections import namedtuple
from contextlib import contextmanager

from pants.base.build_environment import get_buildroot
from pants.base.cmd_line_spec_parser import CmdLineSpecParser
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.bin.options_initializer import OptionsInitializer
from pants.engine.engine import LocalSerialEngine
from pants.engine.fs import create_fs_tasks
from pants.engine.graph import create_graph_tasks
from pants.engine.legacy.graph import LegacyBuildGraph, create_legacy_graph_tasks
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.legacy.structs import JvmAppAdaptor, PythonTargetAdaptor, TargetAdaptor
from pants.engine.mapper import AddressMapper
from pants.engine.parser import SymbolTable
from pants.engine.scheduler import LocalScheduler
from pants.engine.storage import Storage
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
    _, build_config = OptionsInitializer(OptionsBootstrapper()).setup(init_logging=False)
    return build_config.registered_aliases()

  @classmethod
  @memoized_method
  def table(cls):
    aliases = {alias: TargetAdaptor for alias in cls.aliases().target_types}
    # TODO: The alias replacement here is to avoid elevating "TargetAdaptors" into the public
    # API until after https://github.com/pantsbuild/pants/issues/3560 has been completed.
    # These should likely move onto Target subclasses as the engine gets deeper into beta
    # territory.
    aliases['jvm_app'] = JvmAppAdaptor
    for alias in ('python_library', 'python_tests', 'python_binary'):
      aliases[alias] = PythonTargetAdaptor

    return aliases


class LegacyGraphHelper(namedtuple('LegacyGraphHelper', ['scheduler',
                                                         'engine',
                                                         'symbol_table_cls',
                                                         'legacy_graph_cls'])):
  """A container for the components necessary to construct a legacy BuildGraph facade."""

  def create_graph(self, spec_roots):
    """Construct and return a BuildGraph given a set of input specs."""
    graph = self.legacy_graph_cls(self.scheduler, self.engine, self.symbol_table_cls)
    with self.scheduler.locked():
      for _ in graph.inject_specs_closure(spec_roots):  # Ensure the entire generator is unrolled.
        pass
    logger.debug('engine cache stats: %s', self.engine.cache_stats())
    logger.debug('build_graph is: %s', graph)
    return graph


class EngineInitializer(object):
  """Constructs the components necessary to run the v2 engine with v1 BuildGraph compatibility."""

  @staticmethod
  def parse_commandline_to_spec_roots(options=None, args=None, build_root=None):
    if not options:
      options, _ = OptionsInitializer(OptionsBootstrapper(args=args)).setup(init_logging=False)
    cmd_line_spec_parser = CmdLineSpecParser(build_root or get_buildroot())
    spec_roots = [cmd_line_spec_parser.parse_spec(spec) for spec in options.target_specs]
    return spec_roots

  @staticmethod
  def setup_legacy_graph(path_ignore_patterns, symbol_table_cls=None):
    """Construct and return the components necessary for LegacyBuildGraph construction.

    :param list path_ignore_patterns: A list of path ignore patterns for FileSystemProjectTree,
                                      usually taken from the `--pants-ignore` global option.
    :param SymbolTable symbol_table_cls: A SymbolTable class to use for build file parsing, or
                                         None to use the default.
    :returns: A tuple of (scheduler, engine, symbol_table_cls, build_graph_cls).
    """

    build_root = get_buildroot()
    project_tree = FileSystemProjectTree(build_root, path_ignore_patterns)
    symbol_table_cls = symbol_table_cls or LegacySymbolTable

    # Register "literal" subjects required for these tasks.
    # TODO: Replace with `Subsystems`.
    address_mapper = AddressMapper(symbol_table_cls=symbol_table_cls,
                                   parser_cls=LegacyPythonCallbacksParser)

    # Create a Scheduler containing graph and filesystem tasks, with no installed goals. The
    # LegacyBuildGraph will explicitly request the products it needs.
    tasks = (
      create_legacy_graph_tasks() +
      create_fs_tasks() +
      create_graph_tasks(address_mapper, symbol_table_cls)
    )

    scheduler = LocalScheduler(dict(), tasks, project_tree)
    engine = LocalSerialEngine(scheduler, Storage.create(debug=False))

    return LegacyGraphHelper(scheduler, engine, symbol_table_cls, LegacyBuildGraph)

  @classmethod
  @contextmanager
  def open_legacy_graph(cls, options=None, path_ignore_patterns=None, symbol_table_cls=None):
    """A context manager that yields a usable, legacy LegacyBuildGraph by way of the v2 scheduler.

    This is used primarily for testing and non-daemon runs.

    :param Options options: An Options object to use for this run.
    :param list path_ignore_patterns: A list of path ignore patterns for FileSystemProjectTree,
                                      usually taken from the `--pants-ignore` global option.
                                      Defaults to: ['.*']
    :param SymbolTable symbol_table_cls: A SymbolTable class to use for build file parsing, or
                                         None to use the default.
    :yields: A tuple of (graph, addresses, scheduler).
    """
    path_ignore_patterns = path_ignore_patterns or ['.*']
    spec_roots = cls.parse_commandline_to_spec_roots(options=options)
    (scheduler,
     engine,
     symbol_table_cls,
     build_graph_cls) = cls.setup_legacy_graph(path_ignore_patterns, symbol_table_cls=symbol_table_cls)

    engine.start()
    try:
      graph = build_graph_cls(scheduler, engine, symbol_table_cls)
      addresses = tuple(graph.inject_specs_closure(spec_roots))
      yield graph, addresses, scheduler
    finally:
      logger.debug('engine cache stats: {}'.format(engine.cache_stats()))
      engine.close()
