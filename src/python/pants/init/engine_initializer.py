# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Set, Tuple, Type, cast

from pants.base.build_environment import get_buildroot
from pants.base.build_root import BuildRoot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine import interactive_process, process, target
from pants.engine.console import Console
from pants.engine.fs import Workspace, create_fs_rules
from pants.engine.goal import Goal
from pants.engine.interactive_process import InteractiveRunner
from pants.engine.internals import graph, options_parsing
from pants.engine.internals.build_files import create_graph_rules
from pants.engine.internals.mapper import AddressMapper
from pants.engine.internals.native import Native
from pants.engine.internals.parser import Parser, SymbolTable
from pants.engine.internals.scheduler import Scheduler, SchedulerSession
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.platform import create_platform_rules
from pants.engine.rules import RootRule, rule
from pants.engine.selectors import Params
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.global_options import (
    DEFAULT_EXECUTION_OPTIONS,
    ExecutionOptions,
    GlobMatchErrorBehavior,
)
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.scm.subsystems.changed import rules as changed_rules
from pants.subsystem.subsystem import Subsystem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LegacyGraphScheduler:
    """A thin wrapper around a Scheduler configured with @rules for a symbol table."""

    scheduler: Scheduler
    build_file_aliases: Any
    goal_map: Any

    def new_session(
        self, build_id, dynamic_ui: bool = False, use_colors=True, should_report_workunits=False,
    ) -> "LegacyGraphSession":
        session = self.scheduler.new_session(build_id, dynamic_ui, should_report_workunits)
        console = Console(use_colors=use_colors, session=session if dynamic_ui else None,)
        return LegacyGraphSession(session, console, self.build_file_aliases, self.goal_map)


@dataclass(frozen=True)
class LegacyGraphSession:
    """A thin wrapper around a SchedulerSession configured with @rules for a symbol table."""

    scheduler_session: SchedulerSession
    console: Console
    build_file_aliases: Any
    goal_map: Any

    class InvalidGoals(Exception):
        """Raised when invalid v2 goals are passed in a v2-only mode."""

        def __init__(self, invalid_goals):
            super().__init__(
                f"could not satisfy the following goals with @goal_rules: {', '.join(invalid_goals)}"
            )
            self.invalid_goals = invalid_goals

    def goal_consumed_subsystem_scopes(self, goal_name: str) -> Tuple[str, ...]:
        """Return the scopes of subsystems that could be consumed while running the given goal."""
        goal_product = self.goal_map.get(goal_name)
        if not goal_product:
            return tuple()
        consumed_types = self.goal_consumed_types(goal_product)
        return tuple(
            sorted({typ.options_scope for typ in consumed_types if issubclass(typ, Subsystem)})  # type: ignore[misc]
        )

    def goal_consumed_types(self, goal_product: Type) -> Set[Type]:
        """Return the set of types that could possibly be consumed while running the given goal."""
        # NB: Keep this in sync with the method `run_goal_rules`.
        return set(
            self.scheduler_session.scheduler.rule_graph_consumed_types(
                [Specs, Console, InteractiveRunner, OptionsBootstrapper, Workspace], goal_product
            )
        )

    def run_goal_rules(
        self,
        *,
        options_bootstrapper: OptionsBootstrapper,
        union_membership: UnionMembership,
        goals: Iterable[str],
        specs: Specs,
        poll: bool = False,
        poll_delay: Optional[float] = None,
    ) -> int:
        """Runs @goal_rules sequentially and interactively by requesting their implicit Goal
        products.

        For retryable failures, raises scheduler.ExecutionError.

        :returns: An exit code.
        """

        workspace = Workspace(self.scheduler_session)
        interactive_runner = InteractiveRunner(self.scheduler_session)

        for goal in goals:
            goal_product = self.goal_map[goal]
            # NB: We no-op for goals that have no implementation because no relevant backends are
            # registered. We might want to reconsider the behavior to instead warn or error when
            # trying to run something like `./pants run` without any backends registered.
            is_implemented = union_membership.has_members_for_all(
                goal_product.subsystem_cls.required_union_implementations
            )
            if not is_implemented:
                continue
            # NB: Keep this in sync with the method `goal_consumed_types`.
            params = Params(
                specs, options_bootstrapper, self.console, workspace, interactive_runner
            )
            logger.debug(f"requesting {goal_product} to satisfy execution of `{goal}` goal")
            try:
                exit_code = self.scheduler_session.run_goal_rule(
                    goal_product, params, poll=poll, poll_delay=poll_delay
                )
            finally:
                self.console.flush()

            if exit_code != PANTS_SUCCEEDED_EXIT_CODE:
                return exit_code

        return PANTS_SUCCEEDED_EXIT_CODE


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
        options_bootstrapper: OptionsBootstrapper, build_configuration: BuildConfiguration,
    ) -> LegacyGraphScheduler:
        """Construct and return the components necessary for LegacyBuildGraph construction."""
        native = Native()
        build_root = get_buildroot()
        bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
        use_gitignore = bootstrap_options.pants_ignore_use_gitignore

        return EngineInitializer.setup_legacy_graph_extended(
            OptionsInitializer.compute_pants_ignore(build_root, bootstrap_options),
            use_gitignore,
            bootstrap_options.local_store_dir,
            bootstrap_options.local_execution_root_dir,
            bootstrap_options.named_caches_dir,
            bootstrap_options.build_file_prelude_globs,
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
        local_store_dir: str,
        local_execution_root_dir: str,
        named_caches_dir: str,
        build_file_prelude_globs: Tuple[str, ...],
        options_bootstrapper: OptionsBootstrapper,
        build_configuration: BuildConfiguration,
        execution_options: ExecutionOptions,
        build_root: Optional[str] = None,
        native: Optional[Native] = None,
        glob_match_error_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.warn,
        build_ignore_patterns=None,
        exclude_target_regexps=None,
        subproject_roots=None,
        include_trace_on_error: bool = True,
    ) -> LegacyGraphScheduler:
        """Construct and return the components necessary for LegacyBuildGraph construction.

        :param local_store_dir: The directory to use for storing the engine's LMDB store in.
        :param local_execution_root_dir: The directory to use for local execution sandboxes.
        :param named_caches_dir: The base directory for named cache storage.
        :param build_file_prelude_globs: Globs to match files to be prepended to all BUILD files.
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
        execution_options = execution_options or DEFAULT_EXECUTION_OPTIONS

        build_file_aliases = build_configuration.registered_aliases()
        rules = build_configuration.rules()

        registered_target_types = RegisteredTargetTypes.create(build_configuration.target_types())
        symbol_table_from_registered_targets = SymbolTable(
            {target_type.alias: TargetAdaptor for target_type in registered_target_types.types}
        )
        parser = Parser(symbol_table_from_registered_targets, build_file_aliases)
        address_mapper = AddressMapper(
            parser=parser,
            prelude_glob_patterns=build_file_prelude_globs,
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
            return symbol_table_from_registered_targets

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
            *interactive_process.rules(),
            *graph.rules(),
            *options_parsing.rules(),
            *process.rules(),
            *target.rules(),
            *create_fs_rules(),
            *create_platform_rules(),
            *create_graph_rules(address_mapper),
            *changed_rules(),
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
            local_execution_root_dir=local_execution_root_dir,
            named_caches_dir=named_caches_dir,
            rules=rules,
            union_rules=union_rules,
            execution_options=execution_options,
            include_trace_on_error=include_trace_on_error,
            visualize_to_dir=bootstrap_options.native_engine_visualize_to,
        )

        return LegacyGraphScheduler(scheduler, build_file_aliases, goal_map)
