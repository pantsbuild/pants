# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging

from pants.backend.docgen.targets.doc import Page
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.python.targets.python_app import PythonApp
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.remote_sources import RemoteSources
from pants.engine.build_files import create_graph_rules
from pants.engine.console import Console
from pants.engine.fs import create_fs_rules
from pants.engine.goal import Goal
from pants.engine.isolated_process import create_process_rules
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import LegacyBuildGraph, create_legacy_graph_tasks
from pants.engine.legacy.options_parsing import create_options_parsing_rules
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.legacy.structs import (JvmAppAdaptor, JvmBinaryAdaptor, PageAdaptor,
                                         PantsPluginAdaptor, PythonAppAdaptor, PythonBinaryAdaptor,
                                         PythonTargetAdaptor, PythonTestsAdaptor,
                                         RemoteSourcesAdaptor, TargetAdaptor)
from pants.engine.legacy.structs import rules as structs_rules
from pants.engine.mapper import AddressMapper
from pants.engine.parser import SymbolTable
from pants.engine.platform import create_platform_rules
from pants.engine.rules import RootRule, rule
from pants.engine.scheduler import Scheduler
from pants.engine.selectors import Params
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.global_options import (DEFAULT_EXECUTION_OPTIONS, ExecutionOptions,
                                         GlobMatchErrorBehavior)
from pants.util.objects import datatype


logger = logging.getLogger(__name__)


def _tuplify(v):
  if v is None:
    return None
  if isinstance(v, tuple):
    return v
  if isinstance(v, (list, set)):
    return tuple(v)
  return (v,)


def _compute_default_sources_globs(base_class, target_type):
  """Look up the default source globs for the type, and return as a tuple of (globs, excludes)."""
  if not target_type.supports_default_sources() or target_type.default_sources_globs is None:
    return (None, None)

  globs = _tuplify(target_type.default_sources_globs)
  excludes = _tuplify(target_type.default_sources_exclude_globs)

  return (globs, excludes)


def _apply_default_sources_globs(base_class, target_type):
  """Mutates the given TargetAdaptor subclass to apply default sources from the given legacy target type."""
  globs, excludes = _compute_default_sources_globs(base_class, target_type)
  base_class.default_sources_globs = globs
  base_class.default_sources_exclude_globs = excludes


# TODO: These calls mutate the adaptor classes for some known library types to copy over
# their default source globs while preserving their concrete types. As with the alias replacement
# below, this is a delaying tactic to avoid elevating the TargetAdaptor API.
_apply_default_sources_globs(JvmAppAdaptor, JvmApp)
_apply_default_sources_globs(PythonAppAdaptor, PythonApp)
_apply_default_sources_globs(JvmBinaryAdaptor, JvmBinary)
_apply_default_sources_globs(PageAdaptor, Page)
_apply_default_sources_globs(PythonBinaryAdaptor, PythonBinary)
_apply_default_sources_globs(PythonTargetAdaptor, PythonLibrary)
_apply_default_sources_globs(PythonTestsAdaptor, PythonTests)
_apply_default_sources_globs(RemoteSourcesAdaptor, RemoteSources)


def _legacy_symbol_table(build_file_aliases):
  """Construct a SymbolTable for the given BuildFileAliases.

  :param build_file_aliases: BuildFileAliases to register.
  :type build_file_aliases: :class:`pants.build_graph.build_file_aliases.BuildFileAliases`

  :returns: A SymbolTable.
  """
  table = {
    alias: _make_target_adaptor(TargetAdaptor, target_type)
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
      table[alias] = _make_target_adaptor(
        TargetAdaptor,
        tuple(factory.target_types)[0],
      )

  # TODO: The alias replacement here is to avoid elevating "TargetAdaptors" into the public
  # API until after https://github.com/pantsbuild/pants/issues/3560 has been completed.
  # These should likely move onto Target subclasses as the engine gets deeper into beta
  # territory.
  table['python_library'] = PythonTargetAdaptor
  table['jvm_app'] = JvmAppAdaptor
  table['jvm_binary'] = JvmBinaryAdaptor
  table['python_app'] = PythonAppAdaptor
  table['python_tests'] = PythonTestsAdaptor
  table['python_binary'] = PythonBinaryAdaptor
  table['remote_sources'] = RemoteSourcesAdaptor
  table['page'] = PageAdaptor

  # Note that these don't call _make_target_adaptor because we don't have a handy reference to the
  # types being constructed. They don't have any default_sources behavior, so this should be ok,
  # but if we end up doing more things in _make_target_adaptor, we should make sure they're
  # applied here too.
  table['pants_plugin'] = PantsPluginAdaptor
  table['contrib_plugin'] = PantsPluginAdaptor

  return SymbolTable(table)


def _make_target_adaptor(base_class, target_type):
  """Create an adaptor subclass for the given TargetAdaptor base class and legacy target type."""
  globs, excludes = _compute_default_sources_globs(base_class, target_type)
  if globs is None:
    return base_class

  class GlobsHandlingTargetAdaptor(base_class):
    default_sources_globs = globs
    default_sources_exclude_globs = excludes

  return GlobsHandlingTargetAdaptor


class LegacyGraphScheduler(datatype(['scheduler', 'build_file_aliases', 'goal_map'])):
  """A thin wrapper around a Scheduler configured with @rules for a symbol table."""

  def new_session(self, zipkin_trace_v2, v2_ui=False):
    session = self.scheduler.new_session(zipkin_trace_v2, v2_ui)
    return LegacyGraphSession(session, self.build_file_aliases, self.goal_map)


class LegacyGraphSession(datatype(['scheduler_session', 'build_file_aliases', 'goal_map'])):
  """A thin wrapper around a SchedulerSession configured with @rules for a symbol table."""

  class InvalidGoals(Exception):
    """Raised when invalid v2 goals are passed in a v2-only mode."""

    def __init__(self, invalid_goals):
      super(LegacyGraphSession.InvalidGoals, self).__init__(
        'could not satisfy the following goals with @console_rules: {}'
        .format(', '.join(invalid_goals))
      )
      self.invalid_goals = invalid_goals

  def run_console_rules(self, options_bootstrapper, goals, target_roots):
    """Runs @console_rules sequentially and interactively by requesting their implicit Goal products.

    For retryable failures, raises scheduler.ExecutionError.

    :param list goals: The list of requested goal names as passed on the commandline.
    :param TargetRoots target_roots: The targets root of the request.

    :returns: An exit code.
    """
    subject = target_roots.specs
    console = Console(
      use_colors=options_bootstrapper.bootstrap_options.for_global_scope().colors
    )
    for goal in goals:
      goal_product = self.goal_map[goal]
      params = Params(subject, options_bootstrapper, console)
      logger.debug(f'requesting {goal_product} to satisfy execution of `{goal}` goal')
      try:
        exit_code = self.scheduler_session.run_console_rule(goal_product, params)
      finally:
        console.flush()

      if exit_code != PANTS_SUCCEEDED_EXIT_CODE:
        return exit_code
    return PANTS_SUCCEEDED_EXIT_CODE

  def create_build_graph(self, target_roots, build_root=None):
    """Construct and return a `BuildGraph` given a set of input specs.

    :param TargetRoots target_roots: The targets root of the request.
    :param string build_root: The build root.
    :returns: A tuple of (BuildGraph, AddressMapper).
    """
    logger.debug('target_roots are: %r', target_roots)
    graph = LegacyBuildGraph.create(self.scheduler_session, self.build_file_aliases)
    logger.debug('build_graph is: %s', graph)
    # Ensure the entire generator is unrolled.
    for _ in graph.inject_roots_closure(target_roots):
      pass

    address_mapper = LegacyAddressMapper(self.scheduler_session, build_root or get_buildroot())
    logger.debug('address_mapper is: %s', address_mapper)
    return graph, address_mapper


class EngineInitializer:
  """Constructs the components necessary to run the v2 engine with v1 BuildGraph compatibility."""

  class GoalMappingError(Exception):
    """Raised when a goal cannot be mapped to an @rule."""

  @staticmethod
  def _make_goal_map_from_rules(rules):
    goal_map = {}
    for r in rules:
      output_type = getattr(r, 'output_type', None)
      if not output_type or not issubclass(output_type, Goal):
        continue
      goal = r.output_type.name
      if goal in goal_map:
        raise EngineInitializer.GoalMappingError(
          f'could not map goal `{goal}` to rule `{r}`: already claimed by product `{goal_map[goal]}`'
        )
      goal_map[goal] = r.output_type
    return goal_map

  @staticmethod
  def setup_legacy_graph(native, options_bootstrapper, build_configuration):
    """Construct and return the components necessary for LegacyBuildGraph construction."""
    build_root = get_buildroot()
    bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
    return EngineInitializer.setup_legacy_graph_extended(
      OptionsInitializer.compute_pants_ignore(build_root, bootstrap_options),
      bootstrap_options.local_store_dir,
      bootstrap_options.build_file_imports,
      options_bootstrapper,
      build_configuration,
      build_root=build_root,
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
    local_store_dir,
    build_file_imports_behavior,
    options_bootstrapper,
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
    :param local_store_dir: The directory to use for storing the engine's LMDB store in.
    :param build_file_imports_behavior: How to behave if a BUILD file being parsed tries to use
      import statements. Valid values: "allow", "warn", "error".
    :type build_file_imports_behavior: string
    :param str build_root: A path to be used as the build root. If None, then default is used.
    :param Native native: An instance of the native-engine subsystem.
    :param options_bootstrapper: A `OptionsBootstrapper` object containing bootstrap options.
    :type options_bootstrapper: :class:`pants.options.options_bootstrapper.OptionsBootstrapper`
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
    build_configuration = build_configuration or BuildConfigInitializer.get(options_bootstrapper)
    bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()

    build_file_aliases = build_configuration.registered_aliases()
    rules = build_configuration.rules()

    symbol_table = _legacy_symbol_table(build_file_aliases)

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

    @rule(GlobMatchErrorBehavior, [])
    def glob_match_error_behavior_singleton():
      return glob_match_error_behavior or GlobMatchErrorBehavior.ignore

    @rule(BuildConfiguration, [])
    def build_configuration_singleton():
      return build_configuration

    @rule(SymbolTable, [])
    def symbol_table_singleton():
      return symbol_table

    # Create a Scheduler containing graph and filesystem rules, with no installed goals. The
    # LegacyBuildGraph will explicitly request the products it needs.
    rules = (
      [
        RootRule(Console),
        glob_match_error_behavior_singleton,
        build_configuration_singleton,
        symbol_table_singleton,
      ] +
      create_legacy_graph_tasks() +
      create_fs_rules() +
      create_process_rules() +
      create_platform_rules() +
      create_graph_rules(address_mapper) +
      create_options_parsing_rules() +
      structs_rules() +
      rules
    )

    goal_map = EngineInitializer._make_goal_map_from_rules(rules)

    union_rules = build_configuration.union_rules()

    scheduler = Scheduler(
      native,
      project_tree,
      local_store_dir,
      rules,
      union_rules,
      execution_options,
      include_trace_on_error=include_trace_on_error,
      visualize_to_dir=bootstrap_options.native_engine_visualize_to,
    )

    return LegacyGraphScheduler(scheduler, build_file_aliases, goal_map)
