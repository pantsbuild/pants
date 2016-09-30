# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from collections import namedtuple

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.bin.options_initializer import OptionsInitializer
from pants.engine.engine import LocalSerialEngine
from pants.engine.fs import create_fs_tasks
from pants.engine.graph import create_graph_tasks
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.change_calculator import EngineChangeCalculator
from pants.engine.legacy.graph import LegacyBuildGraph, LegacyTarget, create_legacy_graph_tasks
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.legacy.structs import (JvmAppAdaptor, PythonTargetAdaptor, RemoteSourcesAdaptor,
                                         TargetAdaptor)
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
    aliases['remote_sources'] = RemoteSourcesAdaptor
    for alias in ('python_library', 'python_tests', 'python_binary'):
      aliases[alias] = PythonTargetAdaptor

    return aliases


class LegacyGraphHelper(namedtuple('LegacyGraphHelper', ['scheduler', 'engine', 'symbol_table_cls',
                                                         'change_calculator'])):
  """A container for the components necessary to construct a legacy BuildGraph facade."""

  def warm_product_graph(self, target_roots):
    """Warm the scheduler's `ProductGraph` with `LegacyTarget` products.

    :param TargetRoots target_roots: The targets root of the request.
    """
    logger.debug('warming target_roots for: %r', target_roots)
    request = self.scheduler.execution_request([LegacyTarget], target_roots.as_specs())
    result = self.engine.execute(request)
    if result.error:
      raise result.error

  def create_build_graph(self, target_roots, build_root=None):
    """Construct and return a `BuildGraph` given a set of input specs.

    :param TargetRoots target_roots: The targets root of the request.
    :param string build_root: The build root.
    :returns: A tuple of (BuildGraph, AddressMapper).
    """
    logger.debug('target_roots are: %r', target_roots)
    graph = LegacyBuildGraph(self.scheduler, self.engine, self.symbol_table_cls)
    logger.debug('build_graph is: %s', graph)
    with self.scheduler.locked():
      # Ensure the entire generator is unrolled.
      for _ in graph.inject_specs_closure(target_roots.as_specs()):
        pass

    logger.debug('engine cache stats: %s', self.engine.cache_stats())
    address_mapper = LegacyAddressMapper(self.scheduler, self.engine, build_root or get_buildroot())
    logger.debug('address_mapper is: %s', address_mapper)
    return graph, address_mapper


class EngineInitializer(object):
  """Constructs the components necessary to run the v2 engine with v1 BuildGraph compatibility."""

  @staticmethod
  def setup_legacy_graph(pants_ignore_patterns,
                         build_root=None,
                         symbol_table_cls=None,
                         build_ignore_patterns=None,
                         exclude_target_regexps=None):
    """Construct and return the components necessary for LegacyBuildGraph construction.

    :param list pants_ignore_patterns: A list of path ignore patterns for FileSystemProjectTree,
                                       usually taken from the '--pants-ignore' global option.
    :param str build_root: A path to be used as the build root. If None, then default is used.
    :param SymbolTable symbol_table_cls: A SymbolTable class to use for build file parsing, or
                                         None to use the default.
    :param list build_ignore_patterns: A list of paths ignore patterns used when searching for BUILD
                                       files, usually taken from the '--build-ignore' global option.
    :param list exclude_target_regexps: A list of regular expressions for excluding targets.
    :returns: A tuple of (scheduler, engine, symbol_table_cls, build_graph_cls).
    """

    build_root = build_root or get_buildroot()
    scm = get_scm()
    symbol_table_cls = symbol_table_cls or LegacySymbolTable

    project_tree = FileSystemProjectTree(build_root, pants_ignore_patterns)

    # Register "literal" subjects required for these tasks.
    # TODO: Replace with `Subsystems`.
    address_mapper = AddressMapper(symbol_table_cls=symbol_table_cls,
                                   parser_cls=LegacyPythonCallbacksParser,
                                   build_ignore_patterns=build_ignore_patterns,
                                   exclude_target_regexps=exclude_target_regexps)

    # Create a Scheduler containing graph and filesystem tasks, with no installed goals. The
    # LegacyBuildGraph will explicitly request the products it needs.
    tasks = (
      create_legacy_graph_tasks(symbol_table_cls) +
      create_fs_tasks() +
      create_graph_tasks(address_mapper, symbol_table_cls)
    )

    scheduler = LocalScheduler(dict(), tasks, project_tree)
    # TODO: Do not use the cache yet, as it incurs a high overhead.
    engine = LocalSerialEngine(scheduler, Storage.create(), use_cache=False)
    change_calculator = EngineChangeCalculator(engine, scm) if scm else None

    return LegacyGraphHelper(scheduler, engine, symbol_table_cls, change_calculator)
