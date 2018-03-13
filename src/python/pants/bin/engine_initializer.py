# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
from collections import namedtuple

from pants.base.build_environment import get_buildroot, get_scm
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.base.target_roots import ChangedTargetRoots, LiteralTargetRoots
from pants.engine.build_files import BuildFileAddresses, create_graph_rules
from pants.engine.fs import create_fs_rules
from pants.engine.isolated_process import create_process_rules
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import (LegacyBuildGraph, TransitiveHydratedTargets,
                                       create_legacy_graph_tasks)
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.legacy.structs import (GoTargetAdaptor, JavaLibraryAdaptor, JunitTestsAdaptor,
                                         JvmAppAdaptor, PythonLibraryAdaptor, PythonTargetAdaptor,
                                         PythonTestsAdaptor, RemoteSourcesAdaptor,
                                         ScalaLibraryAdaptor, TargetAdaptor)
from pants.engine.mapper import AddressMapper
from pants.engine.native import Native
from pants.engine.parser import SymbolTable
from pants.engine.scheduler import LocalScheduler
from pants.init.options_initializer import OptionsInitializer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.scm.change_calculator import EngineChangeCalculator


logger = logging.getLogger(__name__)


class LegacySymbolTable(SymbolTable):
  """A v1 SymbolTable facade for use with the v2 engine."""

  def __init__(self, build_file_aliases):
    """
    :param build_file_aliases: BuildFileAliases to register.
    :type build_file_aliases: :class:`pants.build_graph.build_file_aliases.BuildFileAliases`
    """
    self._build_file_aliases = build_file_aliases
    self._table = {alias: TargetAdaptor for alias in build_file_aliases.target_types}

    # TODO: The alias replacement here is to avoid elevating "TargetAdaptors" into the public
    # API until after https://github.com/pantsbuild/pants/issues/3560 has been completed.
    # These should likely move onto Target subclasses as the engine gets deeper into beta
    # territory.
    for alias in ['java_library', 'java_agent', 'javac_plugin']:
      self._table[alias] = JavaLibraryAdaptor
    for alias in ['scala_library', 'scalac_plugin']:
      self._table[alias] = ScalaLibraryAdaptor
    for alias in ['python_library', 'pants_plugin']:
      self._table[alias] = PythonLibraryAdaptor
    for alias in ['go_library', 'go_binary']:
      self._table[alias] = GoTargetAdaptor

    self._table['junit_tests'] = JunitTestsAdaptor
    self._table['jvm_app'] = JvmAppAdaptor
    self._table['python_tests'] = PythonTestsAdaptor
    self._table['python_binary'] = PythonTargetAdaptor
    self._table['remote_sources'] = RemoteSourcesAdaptor

  def aliases(self):
    return self._build_file_aliases

  def table(self):
    return self._table


class LegacyGraphHelper(namedtuple('LegacyGraphHelper', ['scheduler', 'symbol_table',
                                                         'change_calculator'])):
  """A container for the components necessary to construct a legacy BuildGraph facade."""

  def warm_product_graph(self, target_roots):
    """Warm the scheduler's `ProductGraph` with `TransitiveHydratedTargets` products.

    :param TargetRoots target_roots: The targets root of the request.
    """
    logger.debug('warming target_roots for: %r', target_roots)
    if type(target_roots) is ChangedTargetRoots:
      subjects = [BuildFileAddresses(target_roots.addresses)]
    elif type(target_roots) is LiteralTargetRoots:
      subjects = target_roots.specs
    else:
      raise ValueError('Unexpected TargetRoots type: `{}`.'.format(target_roots))
    request = self.scheduler.execution_request([TransitiveHydratedTargets], subjects)
    result = self.scheduler.execute(request)
    if result.error:
      raise result.error

  def create_build_graph(self, target_roots, build_root=None):
    """Construct and return a `BuildGraph` given a set of input specs.

    :param TargetRoots target_roots: The targets root of the request.
    :param string build_root: The build root.
    :returns: A tuple of (BuildGraph, AddressMapper).
    """
    logger.debug('target_roots are: %r', target_roots)
    graph = LegacyBuildGraph.create(self.scheduler, self.symbol_table)
    logger.debug('build_graph is: %s', graph)
    # Ensure the entire generator is unrolled.
    for _ in graph.inject_roots_closure(target_roots):
      pass

    address_mapper = LegacyAddressMapper(self.scheduler, build_root or get_buildroot())
    logger.debug('address_mapper is: %s', address_mapper)
    return graph, address_mapper


class EngineInitializer(object):
  """Constructs the components necessary to run the v2 engine with v1 BuildGraph compatibility."""

  @staticmethod
  def setup_legacy_graph(pants_ignore_patterns,
                         workdir,
                         build_file_imports_behavior,
                         build_root=None,
                         native=None,
                         build_file_aliases=None,
                         build_ignore_patterns=None,
                         exclude_target_regexps=None,
                         subproject_roots=None,
                         include_trace_on_error=True):
    """Construct and return the components necessary for LegacyBuildGraph construction.

    :param list pants_ignore_patterns: A list of path ignore patterns for FileSystemProjectTree,
                                       usually taken from the '--pants-ignore' global option.
    :param str workdir: The pants workdir.
    :param build_file_imports_behavior: How to behave if a BUILD file being parsed tries to use
      import statements. Valid values: "allow", "warn", "error".
    :type build_file_imports_behavior: string
    :param str build_root: A path to be used as the build root. If None, then default is used.
    :param Native native: An instance of the native-engine subsystem.
    :param build_file_aliases: BuildFileAliases to register.
    :type build_file_aliases: :class:`pants.build_graph.build_file_aliases.BuildFileAliases`
    :param list build_ignore_patterns: A list of paths ignore patterns used when searching for BUILD
                                       files, usually taken from the '--build-ignore' global option.
    :param list exclude_target_regexps: A list of regular expressions for excluding targets.
    :param list subproject_roots: Paths that correspond with embedded build roots
                                  under the current build root.
    :param bool include_trace_on_error: If True, when an error occurs, the error message will
                include the graph trace.
    :returns: A tuple of (scheduler, engine, symbol_table, build_graph_cls).
    """

    build_root = build_root or get_buildroot()
    scm = get_scm()

    if not build_file_aliases:
      _, build_config = OptionsInitializer(OptionsBootstrapper()).setup(init_logging=False)
      build_file_aliases = build_config.registered_aliases()

    symbol_table = LegacySymbolTable(build_file_aliases)

    project_tree = FileSystemProjectTree(build_root, pants_ignore_patterns)

    # Register "literal" subjects required for these tasks.
    parser = LegacyPythonCallbacksParser(
      symbol_table,
      build_file_aliases,
      build_file_imports_behavior
    )
    address_mapper = AddressMapper(parser=parser,
                                   build_ignore_patterns=build_ignore_patterns,
                                   exclude_target_regexps=exclude_target_regexps,
                                   subproject_roots=subproject_roots)

    # Load the native backend.
    native = native or Native.create()

    # Create a Scheduler containing graph and filesystem tasks, with no installed goals. The
    # LegacyBuildGraph will explicitly request the products it needs.
    tasks = (
      create_legacy_graph_tasks(symbol_table) +
      create_fs_rules() +
      create_graph_rules(address_mapper, symbol_table) +
      create_process_rules()
    )

    scheduler = LocalScheduler(workdir, dict(), tasks, project_tree, native, include_trace_on_error=include_trace_on_error)
    change_calculator = EngineChangeCalculator(scheduler, symbol_table, scm) if scm else None

    return LegacyGraphHelper(scheduler, symbol_table, change_calculator)
