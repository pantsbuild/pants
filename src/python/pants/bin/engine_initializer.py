# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from collections import namedtuple

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.build_files import create_graph_rules
from pants.engine.engine import LocalSerialEngine
from pants.engine.fs import create_fs_rules
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.change_calculator import EngineChangeCalculator
from pants.engine.legacy.graph import HydratedTargets, LegacyBuildGraph, create_legacy_graph_tasks
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.legacy.structs import (GoTargetAdaptor, JavaLibraryAdaptor, JunitTestsAdaptor,
                                         JvmAppAdaptor, PythonLibraryAdaptor, PythonTargetAdaptor,
                                         PythonTestsAdaptor, RemoteSourcesAdaptor,
                                         ScalaLibraryAdaptor, TargetAdaptor)
from pants.engine.mapper import AddressMapper
from pants.engine.parser import SymbolTable
from pants.engine.scheduler import LocalScheduler
from pants.engine.subsystem.native import Native
from pants.init.options_initializer import OptionsInitializer
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
    for alias in ['java_library', 'java_agent', 'javac_plugin']:
      aliases[alias] = JavaLibraryAdaptor
    for alias in ['scala_library', 'scalac_plugin']:
      aliases[alias] = ScalaLibraryAdaptor
    for alias in ['python_library', 'pants_plugin']:
      aliases[alias] = PythonLibraryAdaptor
    for alias in ['go_library', 'go_binary']:
      aliases[alias] = GoTargetAdaptor

    aliases['junit_tests'] = JunitTestsAdaptor
    aliases['jvm_app'] = JvmAppAdaptor
    aliases['python_tests'] = PythonTestsAdaptor
    aliases['python_binary'] = PythonTargetAdaptor
    aliases['remote_sources'] = RemoteSourcesAdaptor

    return aliases


class LegacyGraphHelper(namedtuple('LegacyGraphHelper', ['scheduler', 'engine', 'symbol_table_cls',
                                                         'change_calculator'])):
  """A container for the components necessary to construct a legacy BuildGraph facade."""

  def warm_product_graph(self, target_roots):
    """Warm the scheduler's `ProductGraph` with `HydratedTargets` products.

    :param TargetRoots target_roots: The targets root of the request.
    """
    logger.debug('warming target_roots for: %r', target_roots)
    request = self.scheduler.execution_request([HydratedTargets], target_roots.as_specs())
    result = self.engine.execute(request)
    if result.error:
      raise result.error

  def create_build_graph(self, target_roots, build_root=None, include_trace_on_error=True):
    """Construct and return a `BuildGraph` given a set of input specs.

    :param TargetRoots target_roots: The targets root of the request.
    :param string build_root: The build root.
    :returns: A tuple of (BuildGraph, AddressMapper).
    """
    logger.debug('target_roots are: %r', target_roots)
    graph = LegacyBuildGraph.create(self.scheduler, self.engine, self.symbol_table_cls,
                                    include_trace_on_error=include_trace_on_error)
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
                         workdir,
                         build_root=None,
                         native=None,
                         symbol_table_cls=None,
                         build_ignore_patterns=None,
                         exclude_target_regexps=None,
                         subproject_roots=None,
                         include_trace_on_error=True):
    """Construct and return the components necessary for LegacyBuildGraph construction.

    :param list pants_ignore_patterns: A list of path ignore patterns for FileSystemProjectTree,
                                       usually taken from the '--pants-ignore' global option.
    :param str workdir: The pants workdir.
    :param str build_root: A path to be used as the build root. If None, then default is used.
    :param Native native: An instance of the native-engine subsystem.
    :param SymbolTable symbol_table_cls: A SymbolTable class to use for build file parsing, or
                                         None to use the default.
    :param list build_ignore_patterns: A list of paths ignore patterns used when searching for BUILD
                                       files, usually taken from the '--build-ignore' global option.
    :param list exclude_target_regexps: A list of regular expressions for excluding targets.
    :param list subproject_roots: Paths that correspond with embedded build roots
                                  under the current build root.
    :param bool include_trace_on_error: If True, when an error occurs, the error message will include the graph trace.
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
                                   exclude_target_regexps=exclude_target_regexps,
                                   subproject_roots=subproject_roots)

    # Load the native backend.
    native = native or Native.Factory.global_instance().create()

    # Create a Scheduler containing graph and filesystem tasks, with no installed goals. The
    # LegacyBuildGraph will explicitly request the products it needs.
    tasks = (
      create_legacy_graph_tasks(symbol_table_cls) +
      create_fs_rules() +
      create_graph_rules(address_mapper, symbol_table_cls)
    )

    # TODO: Do not use the cache yet, as it incurs a high overhead.
    scheduler = LocalScheduler(workdir, dict(), tasks, project_tree, native)
    engine = LocalSerialEngine(scheduler, use_cache=False, include_trace_on_error=include_trace_on_error)
    change_calculator = EngineChangeCalculator(scheduler, engine, symbol_table_cls, scm) if scm else None

    return LegacyGraphHelper(scheduler, engine, symbol_table_cls, change_calculator)
