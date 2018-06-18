# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.base.build_environment import get_buildroot
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.build_files import create_graph_rules
from pants.engine.fs import create_fs_rules
from pants.engine.isolated_process import create_process_rules
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import (LegacyBuildGraph, TransitiveHydratedTargets,
                                       create_legacy_graph_tasks)
from pants.engine.legacy.options_parsing import create_options_parsing_rules
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.legacy.structs import (AppAdaptor, GoTargetAdaptor, JavaLibraryAdaptor,
                                         JunitTestsAdaptor, PythonLibraryAdaptor,
                                         PythonTargetAdaptor, PythonTestsAdaptor,
                                         RemoteSourcesAdaptor, ScalaLibraryAdaptor, TargetAdaptor)
from pants.engine.mapper import AddressMapper
from pants.engine.native import Native
from pants.engine.parser import SymbolTable
from pants.engine.rules import SingletonRule
from pants.engine.scheduler import Scheduler
from pants.init.options_initializer import BuildConfigInitializer
from pants.option.global_options import (DEFAULT_EXECUTION_OPTIONS, ExecutionOptions,
                                         GlobMatchErrorBehavior)
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.util.objects import datatype


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
    self._table['jvm_app'] = AppAdaptor
    self._table['python_app'] = AppAdaptor
    self._table['python_tests'] = PythonTestsAdaptor
    self._table['python_binary'] = PythonTargetAdaptor
    self._table['remote_sources'] = RemoteSourcesAdaptor

  def aliases(self):
    return self._build_file_aliases

  def table(self):
    return self._table


class LegacyGraphScheduler(datatype(['scheduler', 'symbol_table'])):
  """A thin wrapper around a Scheduler configured with @rules for a symbol table."""

  def new_session(self):
    session = self.scheduler.new_session()
    return LegacyGraphSession(session, self.symbol_table)


class LegacyGraphSession(datatype(['scheduler_session', 'symbol_table'])):
  """A thin wrapper around a SchedulerSession configured with @rules for a symbol table."""

  def warm_product_graph(self, target_roots):
    """Warm the scheduler's `ProductGraph` with `TransitiveHydratedTargets` products.

    :param TargetRoots target_roots: The targets root of the request.
    """
    logger.debug('warming target_roots for: %r', target_roots)
    subjects = target_roots.specs
    if not subjects:
      subjects = []
    request = self.scheduler_session.execution_request([TransitiveHydratedTargets], subjects)
    result = self.scheduler_session.execute(request)
    if result.error:
      raise result.error

  def create_build_graph(self, target_roots, build_root=None):
    """Construct and return a `BuildGraph` given a set of input specs.

    :param TargetRoots target_roots: The targets root of the request.
    :param string build_root: The build root.
    :returns: A tuple of (BuildGraph, AddressMapper).
    """
    logger.debug('target_roots are: %r', target_roots)
    graph = LegacyBuildGraph.create(self.scheduler_session, self.symbol_table)
    logger.debug('build_graph is: %s', graph)
    # Ensure the entire generator is unrolled.
    for _ in graph.inject_roots_closure(target_roots):
      pass

    address_mapper = LegacyAddressMapper(self.scheduler_session, build_root or get_buildroot())
    logger.debug('address_mapper is: %s', address_mapper)
    return graph, address_mapper


class EngineInitializer(object):
  """Constructs the components necessary to run the v2 engine with v1 BuildGraph compatibility."""

  @staticmethod
  def setup_legacy_graph(native, bootstrap_options, build_configuration):
    """Construct and return the components necessary for LegacyBuildGraph construction."""
    return EngineInitializer.setup_legacy_graph_extended(
      bootstrap_options.pants_ignore,
      bootstrap_options.pants_workdir,
      bootstrap_options.build_file_imports,
      build_configuration,
      native=native,
      glob_match_error_behavior=bootstrap_options.glob_expansion_failure,
      rules=build_configuration.rules(),
      build_ignore_patterns=bootstrap_options.build_ignore,
      exclude_target_regexps=bootstrap_options.exclude_target_regexp,
      subproject_roots=bootstrap_options.subproject_roots,
      include_trace_on_error=bootstrap_options.print_exception_stacktrace,
      execution_options=ExecutionOptions.from_bootstrap_options(bootstrap_options),
    )

  @staticmethod
  def setup_legacy_graph_extended(
    pants_ignore_patterns,
    workdir,
    build_file_imports_behavior,
    build_configuration,
    build_root=None,
    native=None,
    glob_match_error_behavior=None,
    rules=None,
    build_ignore_patterns=None,
    exclude_target_regexps=None,
    subproject_roots=None,
    include_trace_on_error=True,
    execution_options=None,
  ):
    """Construct and return the components necessary for LegacyBuildGraph construction.

    :param list pants_ignore_patterns: A list of path ignore patterns for FileSystemProjectTree,
                                       usually taken from the '--pants-ignore' global option.
    :param str workdir: The pants workdir.
    :param build_file_imports_behavior: How to behave if a BUILD file being parsed tries to use
      import statements. Valid values: "allow", "warn", "error".
    :type build_file_imports_behavior: string
    :param str build_root: A path to be used as the build root. If None, then default is used.
    :param Native native: An instance of the native-engine subsystem.
    :param build_configuration: The `BuildConfiguration` object to get build file aliases from.
    :type build_configuration: :class:`pants.build_graph.build_configuration.BuildConfiguration`
    :param glob_match_error_behavior: How to behave if a glob specified for a target's sources or
                                      bundles does not expand to anything.
    :type glob_match_error_behavior: :class:`pants.option.global_options.GlobMatchErrorBehavior`
    :param list build_ignore_patterns: A list of paths ignore patterns used when searching for BUILD
                                       files, usually taken from the '--build-ignore' global option.
    :param list exclude_target_regexps: A list of regular expressions for excluding targets.
    :param list subproject_roots: Paths that correspond with embedded build roots
                                  under the current build root.
    :param bool include_trace_on_error: If True, when an error occurs, the error message will
                include the graph trace.
    :param execution_options: Option values for (remote) process execution.
    :type execution_options: :class:`pants.option.global_options.ExecutionOptions`
    :returns: A LegacyGraphScheduler.
    """

    build_root = build_root or get_buildroot()
    build_configuration = build_configuration or BuildConfigInitializer.get(OptionsBootstrapper())
    build_file_aliases = build_configuration.registered_aliases()
    rules = rules or build_configuration.rules() or []

    symbol_table = LegacySymbolTable(build_file_aliases)

    project_tree = FileSystemProjectTree(build_root, pants_ignore_patterns)

    execution_options = execution_options or DEFAULT_EXECUTION_OPTIONS

    # Register "literal" subjects required for these rules.
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

    # Create a Scheduler containing graph and filesystem rules, with no installed goals. The
    # LegacyBuildGraph will explicitly request the products it needs.
    rules = (
      [
        SingletonRule.from_instance(GlobMatchErrorBehavior.create(glob_match_error_behavior)),
        SingletonRule.from_instance(build_configuration),
      ] +
      create_legacy_graph_tasks(symbol_table) +
      create_fs_rules() +
      create_process_rules() +
      create_graph_rules(address_mapper, symbol_table) +
      create_options_parsing_rules() +
      rules
    )

    scheduler = Scheduler(
      native,
      project_tree,
      workdir,
      rules,
      execution_options,
      include_trace_on_error=include_trace_on_error,
    )

    return LegacyGraphScheduler(scheduler, symbol_table)
