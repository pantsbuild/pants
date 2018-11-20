# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
from builtins import object

from pants.backend.docgen.targets.doc import Page
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.python.rules.python_test_runner import run_python_test
from pants.backend.python.targets.python_app import PythonApp
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.build_graph.remote_sources import RemoteSources
from pants.engine.build_files import create_graph_rules
from pants.engine.console import Console
from pants.engine.fs import create_fs_rules
from pants.engine.isolated_process import create_process_rules
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import (LegacyBuildGraph, TransitiveHydratedTargets,
                                       create_legacy_graph_tasks)
from pants.engine.legacy.options_parsing import create_options_parsing_rules
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.legacy.structs import (AppAdaptor, JvmBinaryAdaptor, PageAdaptor,
                                         PantsPluginAdaptor, PythonBinaryAdaptor,
                                         PythonTargetAdaptor, PythonTestsAdaptor,
                                         RemoteSourcesAdaptor, TargetAdaptor)
from pants.engine.mapper import AddressMapper
from pants.engine.native import Native
from pants.engine.parser import SymbolTable
from pants.engine.rules import SingletonRule
from pants.engine.scheduler import Scheduler
from pants.init.options_initializer import BuildConfigInitializer
from pants.option.global_options import (DEFAULT_EXECUTION_OPTIONS, ExecutionOptions,
                                         GlobMatchErrorBehavior)
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.rules.core.register import create_core_rules
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
    self._table = {
      alias: self._make_target_adaptor(TargetAdaptor, target_type)
      for alias, target_type in build_file_aliases.target_types.items()
    }

    for alias, factory in build_file_aliases.target_macro_factories.items():
      # TargetMacro.Factory with more than one target type is deprecated.
      # For default sources, this means that TargetMacro Factories with more than one target_type
      # will not parse sources through the engine, and will fall back to the legacy python sources
      # parsing.
      # Conveniently, multi-target_type TargetMacro.Factory, and legacy python source parsing, are
      # targeted to be removed in the same version of pants.
      if len(factory.target_types) == 1:
        self._table[alias] = self._make_target_adaptor(
          TargetAdaptor,
          tuple(factory.target_types)[0],
        )

    # TODO: The alias replacement here is to avoid elevating "TargetAdaptors" into the public
    # API until after https://github.com/pantsbuild/pants/issues/3560 has been completed.
    # These should likely move onto Target subclasses as the engine gets deeper into beta
    # territory.
    self._table['python_library'] = self._make_target_adaptor(PythonTargetAdaptor, PythonLibrary)

    self._table['jvm_app'] = self._make_target_adaptor(AppAdaptor, JvmApp)
    self._table['jvm_binary'] = self._make_target_adaptor(JvmBinaryAdaptor, JvmBinary)
    self._table['python_app'] = self._make_target_adaptor(AppAdaptor, PythonApp)
    self._table['python_tests'] = self._make_target_adaptor(PythonTestsAdaptor, PythonTests)
    self._table['python_binary'] = self._make_target_adaptor(PythonBinaryAdaptor, PythonBinary)
    self._table['remote_sources'] = self._make_target_adaptor(RemoteSourcesAdaptor, RemoteSources)
    self._table['page'] = self._make_target_adaptor(PageAdaptor, Page)

    # Note that these don't call _make_target_adaptor because we don't have a handy reference to the
    # types being constructed. They don't have any default_sources behavior, so this should be ok,
    # but if we end up doing more things in _make_target_adaptor, we should make sure they're
    # applied here too.
    self._table['pants_plugin'] = PantsPluginAdaptor
    self._table['contrib_plugin'] = PantsPluginAdaptor

  def aliases(self):
    return self._build_file_aliases

  def table(self):
    return self._table

  @classmethod
  def _make_target_adaptor(cls, base_class, target_type):
    """
    Look up the default source globs for the type, and apply them to parsing through the engine.
    """
    if not target_type.supports_default_sources() or target_type.default_sources_globs is None:
      return base_class

    globs = _tuplify(target_type.default_sources_globs)
    excludes = _tuplify(target_type.default_sources_exclude_globs)

    class GlobsHandlingTargetAdaptor(base_class):
      @property
      def default_sources_globs(self):
        if globs is None:
          return super(GlobsHandlingTargetAdaptor, self).default_sources_globs
        else:
          return globs

      @property
      def default_sources_exclude_globs(self):
        if excludes is None:
          return super(GlobsHandlingTargetAdaptor, self).default_sources_exclude_globs
        else:
          return excludes

    return GlobsHandlingTargetAdaptor


def _tuplify(v):
  if v is None:
    return None
  if isinstance(v, tuple):
    return v
  if isinstance(v, (list, set)):
    return tuple(v)
  return (v,)


class LegacyGraphScheduler(datatype(['scheduler', 'symbol_table', 'goal_map'])):
  """A thin wrapper around a Scheduler configured with @rules for a symbol table."""

  def new_session(self):
    session = self.scheduler.new_session()
    return LegacyGraphSession(session, self.symbol_table, self.goal_map)


class LegacyGraphSession(datatype(['scheduler_session', 'symbol_table', 'goal_map'])):
  """A thin wrapper around a SchedulerSession configured with @rules for a symbol table."""

  class InvalidGoals(Exception):
    """Raised when invalid v2 goals are passed in a v2-only mode."""

    def __init__(self, invalid_goals):
      super(LegacyGraphSession.InvalidGoals, self).__init__(
        'could not satisfy the following goals with @console_rules: {}'
        .format(', '.join(invalid_goals))
      )
      self.invalid_goals = invalid_goals

  @staticmethod
  def _determine_subjects(target_roots):
    """A utility to determines the subjects for the request.

    :param TargetRoots target_roots: The targets root of the request.
    """
    return target_roots.specs or []

  def warm_product_graph(self, target_roots):
    """Warm the scheduler's `ProductGraph` with `TransitiveHydratedTargets` products.

    This method raises only fatal errors, and does not consider failed roots in the execution
    graph: in the v1 codepath, failed roots are accounted for post-fork.

    :param TargetRoots target_roots: The targets root of the request.
    """
    logger.debug('warming target_roots for: %r', target_roots)
    subjects = self._determine_subjects(target_roots)
    request = self.scheduler_session.execution_request([TransitiveHydratedTargets], subjects)
    result = self.scheduler_session.execute(request)
    if result.error:
      raise result.error

  def validate_goals(self, goals):
    """Checks for @console_rules that satisfy requested goals.

    :param list goals: The list of requested goal names as passed on the commandline.
    """
    invalid_goals = [goal for goal in goals if goal not in self.goal_map]
    if invalid_goals:
      raise self.InvalidGoals(invalid_goals)

  def run_console_rules(self, goals, target_roots, v2_ui):
    """Runs @console_rules sequentially and interactively by requesting their implicit Goal products.

    For retryable failures, raises scheduler.ExecutionError.

    :param list goals: The list of requested goal names as passed on the commandline.
    :param TargetRoots target_roots: The targets root of the request.
    :param bool v2_ui: whether to render the v2 engine UI
    """
    # Reduce to only applicable goals - with validation happening by way of `validate_goals()`.
    goals = [goal for goal in goals if goal in self.goal_map]
    subjects = self._determine_subjects(target_roots)
    # Console rule can only have one subject.
    assert len(subjects) == 1
    for goal in goals:
      goal_product = self.goal_map[goal]
      logger.debug('requesting {} to satisfy execution of `{}` goal'.format(goal_product, goal))
      self.scheduler_session.run_console_rule(goal_product, subjects[0], v2_ui)

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

  class GoalMappingError(Exception):
    """Raised when a goal cannot be mapped to an @rule."""

  @staticmethod
  def _make_goal_map_from_rules(rules):
    goal_map = {}
    goal_to_rule = [(rule.goal, rule) for rule in rules if getattr(rule, 'goal', None) is not None]
    for goal, rule in goal_to_rule:
      if goal in goal_map:
        raise EngineInitializer.GoalMappingError(
          'could not map goal `{}` to rule `{}`: already claimed by product `{}`'
          .format(goal, rule, goal_map[goal])
        )
      goal_map[goal] = rule.output_type
    return goal_map

  @staticmethod
  def setup_legacy_graph(native, bootstrap_options, build_configuration):
    """Construct and return the components necessary for LegacyBuildGraph construction."""
    return EngineInitializer.setup_legacy_graph_extended(
      bootstrap_options.pants_ignore,
      bootstrap_options.pants_workdir,
      bootstrap_options.local_store_dir,
      bootstrap_options.build_file_imports,
      build_configuration,
      native=native,
      glob_match_error_behavior=bootstrap_options.glob_expansion_failure,
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
    local_store_dir,
    build_file_imports_behavior,
    build_configuration,
    build_root=None,
    native=None,
    glob_match_error_behavior=None,
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
    :param local_store_dir: The directory to use for storing the engine's LMDB store in.
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
    rules = build_configuration.rules()
    console = Console()

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
        SingletonRule.from_instance(console),
        SingletonRule.from_instance(GlobMatchErrorBehavior.create(glob_match_error_behavior)),
        SingletonRule.from_instance(build_configuration),
      ] +
      create_legacy_graph_tasks(symbol_table) +
      create_fs_rules() +
      create_process_rules() +
      create_graph_rules(address_mapper, symbol_table) +
      create_options_parsing_rules() +
      create_core_rules() +
      # TODO: This should happen automatically, but most tests (e.g. tests/python/pants_test/auth) fail if it's not here:
      [run_python_test] +
      rules
    )

    goal_map = EngineInitializer._make_goal_map_from_rules(rules)

    scheduler = Scheduler(
      native,
      project_tree,
      workdir,
      local_store_dir,
      rules,
      execution_options,
      include_trace_on_error=include_trace_on_error,
    )

    return LegacyGraphScheduler(scheduler, symbol_table, goal_map)
