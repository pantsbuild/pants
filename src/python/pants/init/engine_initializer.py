# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Tuple, Type, cast

from pants.backend.docgen.targets.doc import Page
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.python.targets.python_app import PythonApp
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.build_root import BuildRoot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import Specs
from pants.binaries.binary_tool import rules as binary_tool_rules
from pants.binaries.binary_util import rules as binary_util_rules
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.remote_sources import RemoteSources
from pants.build_graph.target import Target as TargetV1
from pants.engine.build_files import create_graph_rules
from pants.engine.console import Console
from pants.engine.fs import Workspace, create_fs_rules
from pants.engine.goal import Goal
from pants.engine.interactive_runner import InteractiveRunner, create_interactive_runner_rules
from pants.engine.isolated_process import create_process_rules
from pants.engine.legacy.address_mapper import LegacyAddressMapper
from pants.engine.legacy.graph import LegacyBuildGraph, create_legacy_graph_tasks
from pants.engine.legacy.options_parsing import create_options_parsing_rules
from pants.engine.legacy.parser import LegacyPythonCallbacksParser
from pants.engine.legacy.structs import (
    JvmAppAdaptor,
    JvmBinaryAdaptor,
    PageAdaptor,
    PantsPluginAdaptor,
    PythonAppAdaptor,
    PythonBinaryAdaptor,
    PythonTargetAdaptor,
    PythonTestsAdaptor,
    RemoteSourcesAdaptor,
    TargetAdaptor,
)
from pants.engine.legacy.structs import rules as structs_rules
from pants.engine.mapper import AddressMapper
from pants.engine.native import Native
from pants.engine.parser import SymbolTable
from pants.engine.platform import create_platform_rules
from pants.engine.rules import RootRule, UnionMembership, rule
from pants.engine.scheduler import Scheduler, SchedulerSession
from pants.engine.selectors import Params
from pants.engine.target import RegisteredTargetTypes
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.global_options import (
    DEFAULT_EXECUTION_OPTIONS,
    BuildFileImportsBehavior,
    ExecutionOptions,
    GlobMatchErrorBehavior,
)
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.scm.subsystems.changed import rules as changed_rules

logger = logging.getLogger(__name__)


def _tuplify(v: Optional[Iterable]) -> Optional[Tuple]:
    if v is None:
        return None
    if isinstance(v, tuple):
        return v
    if isinstance(v, (list, set)):
        return tuple(v)
    return (v,)


def _compute_default_sources_globs(
    v1_target_cls: Type[TargetV1],
) -> Tuple[Optional[Tuple[str, ...]], Optional[Tuple[str, ...]]]:
    """Look up the default source globs for the type, and return as a tuple of (globs, excludes)."""
    if not v1_target_cls.supports_default_sources() or v1_target_cls.default_sources_globs is None:
        return (None, None)

    globs = _tuplify(v1_target_cls.default_sources_globs)
    excludes = _tuplify(v1_target_cls.default_sources_exclude_globs)

    return (globs, excludes)


def _apply_default_sources_globs(
    adaptor_cls: Type[TargetAdaptor], v1_target_cls: Type[TargetV1]
) -> None:
    """Mutates the given TargetAdaptor subclass to apply default sources from the given legacy
    target type."""
    globs, excludes = _compute_default_sources_globs(v1_target_cls)
    adaptor_cls.default_sources_globs = globs  # type: ignore[assignment]
    adaptor_cls.default_sources_exclude_globs = excludes  # type: ignore[assignment]


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


def _make_target_adaptor(
    adaptor_cls: Type[TargetAdaptor], v1_target_cls: Type[TargetV1]
) -> Type[TargetAdaptor]:
    """Create an adaptor subclass for the given TargetAdaptor base class and legacy target type."""
    globs, excludes = _compute_default_sources_globs(v1_target_cls)
    if globs is None:
        return adaptor_cls

    class GlobsHandlingTargetAdaptor(adaptor_cls):  # type: ignore[misc,valid-type]
        default_sources_globs = globs
        default_sources_exclude_globs = excludes

    return GlobsHandlingTargetAdaptor


def _legacy_symbol_table(
    build_file_aliases: BuildFileAliases, registered_target_types: RegisteredTargetTypes
) -> SymbolTable:
    """Construct a SymbolTable for the given BuildFileAliases."""
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
            table[alias] = _make_target_adaptor(TargetAdaptor, tuple(factory.target_types)[0],)

    # Now, register any target types only declared in V2 without a V1 equivalent.
    table.update(
        {
            target_type.alias: TargetAdaptor
            for target_type in registered_target_types.types
            if target_type.alias not in table
        }
    )

    table["python_library"] = PythonTargetAdaptor
    table["jvm_app"] = JvmAppAdaptor
    table["jvm_binary"] = JvmBinaryAdaptor
    table["python_app"] = PythonAppAdaptor
    table["python_tests"] = PythonTestsAdaptor
    table["python_binary"] = PythonBinaryAdaptor
    table["remote_sources"] = RemoteSourcesAdaptor
    table["page"] = PageAdaptor
    table["pants_plugin"] = PantsPluginAdaptor
    table["contrib_plugin"] = PantsPluginAdaptor

    return SymbolTable(table)


@dataclass(frozen=True)
class LegacyGraphScheduler:
    """A thin wrapper around a Scheduler configured with @rules for a symbol table."""

    scheduler: Scheduler
    build_file_aliases: Any
    goal_map: Any

    def new_session(
        self, zipkin_trace_v2, build_id, v2_ui=False, should_report_workunits=False
    ) -> "LegacyGraphSession":
        session = self.scheduler.new_session(
            zipkin_trace_v2, build_id, v2_ui, should_report_workunits
        )
        return LegacyGraphSession(session, self.build_file_aliases, self.goal_map)


@dataclass(frozen=True)
class LegacyGraphSession:
    """A thin wrapper around a SchedulerSession configured with @rules for a symbol table."""

    scheduler_session: SchedulerSession
    build_file_aliases: Any
    goal_map: Any

    class InvalidGoals(Exception):
        """Raised when invalid v2 goals are passed in a v2-only mode."""

        def __init__(self, invalid_goals):
            super().__init__(
                f"could not satisfy the following goals with @goal_rules: {', '.join(invalid_goals)}"
            )
            self.invalid_goals = invalid_goals

    def run_goal_rules(
        self,
        *,
        options_bootstrapper: OptionsBootstrapper,
        union_membership: UnionMembership,
        options: Options,
        goals: Iterable[str],
        specs: Specs,
    ) -> int:
        """Runs @goal_rules sequentially and interactively by requesting their implicit Goal
        products.

        For retryable failures, raises scheduler.ExecutionError.

        :returns: An exit code.
        """

        global_options = options.for_global_scope()

        console = Console(
            use_colors=global_options.colors,
            session=self.scheduler_session if global_options.get("v2_ui") else None,
        )
        workspace = Workspace(self.scheduler_session)
        interactive_runner = InteractiveRunner(self.scheduler_session)

        for goal in goals:
            goal_product = self.goal_map[goal]
            # NB: We no-op for goals that have no V2 implementation because no relevant backends are
            # registered. This allows us to safely set `--v1 --v2`, even if no V2 backends are registered.
            # Once V1 is removed, we might want to reconsider the behavior to instead warn or error when
            # trying to run something like `./pants run` without any backends registered.
            is_implemented = union_membership.has_members_for_all(
                goal_product.subsystem_cls.required_union_implementations
            )
            if not is_implemented:
                continue
            params = Params(
                specs.provided_specs, options_bootstrapper, console, workspace, interactive_runner,
            )
            logger.debug(f"requesting {goal_product} to satisfy execution of `{goal}` goal")
            try:
                exit_code = self.scheduler_session.run_goal_rule(goal_product, params)
            finally:
                console.flush()

            if exit_code != PANTS_SUCCEEDED_EXIT_CODE:
                return exit_code

        return PANTS_SUCCEEDED_EXIT_CODE

    def create_build_graph(
        self, specs: Specs, build_root: Optional[str] = None,
    ) -> Tuple[LegacyBuildGraph, LegacyAddressMapper]:
        """Construct and return a `BuildGraph` given a set of input specs."""
        logger.debug("specs are: %r", specs)
        graph = LegacyBuildGraph.create(self.scheduler_session, self.build_file_aliases)
        logger.debug("build_graph is: %s", graph)
        # Ensure the entire generator is unrolled.
        for _ in graph.inject_roots_closure(specs.address_specs):
            pass

        address_mapper = LegacyAddressMapper(self.scheduler_session, build_root or get_buildroot())
        logger.debug("address_mapper is: %s", address_mapper)
        return graph, address_mapper


class EngineInitializer:
    """Constructs the components necessary to run the v2 engine with v1 BuildGraph compatibility."""

    class GoalMappingError(Exception):
        """Raised when a goal cannot be mapped to an @rule."""

    @staticmethod
    def _make_goal_map_from_rules(rules):
        goal_map = {}
        for r in rules:
            output_type = getattr(r, "output_type", None)
            if not output_type or not issubclass(output_type, Goal):
                continue
            goal = r.output_type.name
            if goal in goal_map:
                raise EngineInitializer.GoalMappingError(
                    f"could not map goal `{goal}` to rule `{r}`: already claimed by product `{goal_map[goal]}`"
                )
            goal_map[goal] = r.output_type
        return goal_map

    @staticmethod
    def setup_legacy_graph(
        native: Native,
        options_bootstrapper: OptionsBootstrapper,
        build_configuration: BuildConfiguration,
    ) -> LegacyGraphScheduler:
        """Construct and return the components necessary for LegacyBuildGraph construction."""
        build_root = get_buildroot()
        bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
        use_gitignore = bootstrap_options.pants_ignore_use_gitignore

        return EngineInitializer.setup_legacy_graph_extended(
            OptionsInitializer.compute_pants_ignore(build_root, bootstrap_options),
            use_gitignore,
            bootstrap_options.local_store_dir,
            bootstrap_options.build_file_imports,
            options_bootstrapper,
            build_configuration,
            build_root=build_root,
            native=native,
            glob_match_error_behavior=(
                bootstrap_options.files_not_found_behavior.to_glob_match_error_behavior()
            ),
            build_ignore_patterns=bootstrap_options.build_ignore,
            exclude_target_regexps=bootstrap_options.exclude_target_regexp,
            subproject_roots=bootstrap_options.subproject_roots,
            include_trace_on_error=bootstrap_options.print_exception_stacktrace,
            execution_options=ExecutionOptions.from_bootstrap_options(bootstrap_options),
        )

    @staticmethod
    def setup_legacy_graph_extended(
        pants_ignore_patterns: List[str],
        use_gitignore: bool,
        local_store_dir,
        build_file_imports_behavior: BuildFileImportsBehavior,
        options_bootstrapper: OptionsBootstrapper,
        build_configuration: BuildConfiguration,
        build_root: Optional[str] = None,
        native: Optional[Native] = None,
        glob_match_error_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.warn,
        build_ignore_patterns=None,
        exclude_target_regexps=None,
        subproject_roots=None,
        include_trace_on_error: bool = True,
        execution_options: Optional[ExecutionOptions] = None,
    ) -> LegacyGraphScheduler:
        """Construct and return the components necessary for LegacyBuildGraph construction.

        :param local_store_dir: The directory to use for storing the engine's LMDB store in.
        :param build_file_imports_behavior: How to behave if a BUILD file being parsed tries to use
                                            import statements.
        :param build_root: A path to be used as the build root. If None, then default is used.
        :param native: An instance of the native-engine subsystem.
        :param options_bootstrapper: A `OptionsBootstrapper` object containing bootstrap options.
        :param build_configuration: The `BuildConfiguration` object to get build file aliases from.
        :param glob_match_error_behavior: How to behave if a glob specified for a target's sources or
                                          bundles does not expand to anything.
        :param list build_ignore_patterns: A list of paths ignore patterns used when searching for BUILD
                                           files, usually taken from the '--build-ignore' global option.
        :param list exclude_target_regexps: A list of regular expressions for excluding targets.
        :param list subproject_roots: Paths that correspond with embedded build roots
                                      under the current build root.
        :param include_trace_on_error: If True, when an error occurs, the error message will include
                                       the graph trace.
        :param execution_options: Option values for (remote) process execution.
        """

        build_root = build_root or get_buildroot()
        build_configuration = build_configuration or BuildConfigInitializer.get(
            options_bootstrapper
        )
        bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()

        build_file_aliases = build_configuration.registered_aliases()
        rules = build_configuration.rules()

        registered_target_types = RegisteredTargetTypes.create(build_configuration.targets())

        symbol_table = _legacy_symbol_table(build_file_aliases, registered_target_types)

        execution_options = execution_options or DEFAULT_EXECUTION_OPTIONS

        # Register "literal" subjects required for these rules.
        parser = LegacyPythonCallbacksParser(
            symbol_table, build_file_aliases, build_file_imports_behavior
        )
        address_mapper = AddressMapper(
            parser=parser,
            build_ignore_patterns=build_ignore_patterns,
            exclude_target_regexps=exclude_target_regexps,
            subproject_roots=subproject_roots,
        )

        @rule
        def glob_match_error_behavior_singleton() -> GlobMatchErrorBehavior:
            return glob_match_error_behavior

        @rule
        def build_configuration_singleton() -> BuildConfiguration:
            return build_configuration

        @rule
        def symbol_table_singleton() -> SymbolTable:
            return symbol_table

        @rule
        def registered_target_types_singleton() -> RegisteredTargetTypes:
            return registered_target_types

        @rule
        def union_membership_singleton() -> UnionMembership:
            return UnionMembership(build_configuration.union_rules())

        @rule
        def build_root_singleton() -> BuildRoot:
            return cast(BuildRoot, BuildRoot.instance)

        # Create a Scheduler containing graph and filesystem rules, with no installed goals. The
        # LegacyBuildGraph will explicitly request the products it needs.
        rules = (
            RootRule(Console),
            glob_match_error_behavior_singleton,
            build_configuration_singleton,
            symbol_table_singleton,
            registered_target_types_singleton,
            union_membership_singleton,
            build_root_singleton,
            *create_legacy_graph_tasks(),
            *create_fs_rules(),
            *create_interactive_runner_rules(),
            *create_process_rules(),
            *create_platform_rules(),
            *create_graph_rules(address_mapper),
            *create_options_parsing_rules(),
            *structs_rules(),
            *changed_rules(),
            *binary_tool_rules(),
            *binary_util_rules(),
            *rules,
        )

        goal_map = EngineInitializer._make_goal_map_from_rules(rules)

        union_rules = build_configuration.union_rules()

        scheduler = Scheduler(
            native=native,
            ignore_patterns=pants_ignore_patterns,
            use_gitignore=use_gitignore,
            build_root=build_root,
            local_store_dir=local_store_dir,
            rules=rules,
            union_rules=union_rules,
            execution_options=execution_options,
            include_trace_on_error=include_trace_on_error,
            visualize_to_dir=bootstrap_options.native_engine_visualize_to,
        )

        return LegacyGraphScheduler(scheduler, build_file_aliases, goal_map)
