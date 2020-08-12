# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set, Tuple, Type, cast

from pants.base.build_environment import get_buildroot
from pants.base.build_root import BuildRoot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine import fs, process
from pants.engine.console import Console
from pants.engine.fs import Workspace
from pants.engine.goal import Goal
from pants.engine.internals import build_files, graph, options_parsing, uuid
from pants.engine.internals.mapper import AddressMapper
from pants.engine.internals.native import Native
from pants.engine.internals.parser import Parser
from pants.engine.internals.scheduler import Scheduler, SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.platform import create_platform_rules
from pants.engine.process import InteractiveRunner
from pants.engine.rules import RootRule, collect_rules, rule
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership
from pants.init.options_initializer import BuildConfigInitializer, OptionsInitializer
from pants.option.global_options import (
    DEFAULT_EXECUTION_OPTIONS,
    ExecutionOptions,
    FilesNotFoundBehavior,
)
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.subsystem import Subsystem
from pants.scm.subsystems.changed import rules as changed_rules
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphScheduler:
    """A thin wrapper around a Scheduler configured with @rules."""

    scheduler: Scheduler
    goal_map: Any

    def new_session(
        self, build_id, dynamic_ui: bool = False, use_colors=True, should_report_workunits=False,
    ) -> "GraphSession":
        session = self.scheduler.new_session(build_id, dynamic_ui, should_report_workunits)
        console = Console(use_colors=use_colors, session=session if dynamic_ui else None)
        return GraphSession(session, console, self.goal_map)


@dataclass(frozen=True)
class GraphSession:
    """A thin wrapper around a SchedulerSession configured with @rules."""

    scheduler_session: SchedulerSession
    console: Console
    goal_map: Any

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
    """Constructs the components necessary to run the engine."""

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
                    f"could not map goal `{goal}` to rule `{r}`: already claimed by product "
                    f"`{goal_map[goal]}`"
                )
            goal_map[goal] = r.output_type
        return goal_map

    @staticmethod
    def setup_graph(
        options_bootstrapper: OptionsBootstrapper, build_configuration: BuildConfiguration,
    ) -> GraphScheduler:
        native = Native()
        build_root = get_buildroot()
        bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
        return EngineInitializer.setup_graph_extended(
            options_bootstrapper,
            build_configuration,
            ExecutionOptions.from_bootstrap_options(bootstrap_options),
            files_not_found_behavior=bootstrap_options.files_not_found_behavior,
            pants_ignore_patterns=OptionsInitializer.compute_pants_ignore(
                build_root, bootstrap_options
            ),
            use_gitignore=bootstrap_options.pants_ignore_use_gitignore,
            local_store_dir=bootstrap_options.local_store_dir,
            local_execution_root_dir=bootstrap_options.local_execution_root_dir,
            named_caches_dir=bootstrap_options.named_caches_dir,
            build_root=build_root,
            native=native,
            include_trace_on_error=bootstrap_options.print_exception_stacktrace,
        )

    @staticmethod
    def setup_graph_extended(
        options_bootstrapper: OptionsBootstrapper,
        build_configuration: BuildConfiguration,
        execution_options: ExecutionOptions,
        native: Native,
        *,
        files_not_found_behavior: FilesNotFoundBehavior,
        pants_ignore_patterns: List[str],
        use_gitignore: bool,
        local_store_dir: str,
        local_execution_root_dir: str,
        named_caches_dir: str,
        build_root: Optional[str] = None,
        include_trace_on_error: bool = True,
    ) -> GraphScheduler:
        build_root = build_root or get_buildroot()

        build_configuration = build_configuration or BuildConfigInitializer.get(
            options_bootstrapper
        )
        rules = build_configuration.rules
        union_membership = UnionMembership.from_rules(build_configuration.union_rules)
        registered_target_types = RegisteredTargetTypes.create(build_configuration.target_types)

        bootstrap_options = options_bootstrapper.bootstrap_options.for_global_scope()
        execution_options = execution_options or DEFAULT_EXECUTION_OPTIONS

        # TODO(#10569): move this out of engine_initializer.py into a normal rule that sets up
        #  AddressMapper.
        parser = Parser(
            target_type_aliases=registered_target_types.aliases,
            object_aliases=build_configuration.registered_aliases,
        )
        address_mapper = AddressMapper(
            parser=parser,
            prelude_glob_patterns=bootstrap_options.build_file_prelude_globs,
            build_patterns=bootstrap_options.build_patterns,
            build_ignore_patterns=bootstrap_options.build_ignore,
        )

        @rule
        def address_mapper_singleton() -> AddressMapper:
            return address_mapper

        # TODO(#10569): move this out of engine_initializer.py into a normal rule.
        @rule
        def files_not_found_behavior_singleton() -> FilesNotFoundBehavior:
            return files_not_found_behavior

        @rule
        def build_configuration_singleton() -> BuildConfiguration:
            return build_configuration

        @rule
        def registered_target_types_singleton() -> RegisteredTargetTypes:
            return registered_target_types

        @rule
        def union_membership_singleton() -> UnionMembership:
            return union_membership

        @rule
        def build_root_singleton() -> BuildRoot:
            return cast(BuildRoot, BuildRoot.instance)

        # Create a Scheduler containing graph and filesystem rules, with no installed goals.
        rules = FrozenOrderedSet(
            (
                *collect_rules(locals()),
                RootRule(Console),
                *build_files.rules(),
                *fs.rules(),
                *graph.rules(),
                *uuid.rules(),
                *options_parsing.rules(),
                *process.rules(),
                *create_platform_rules(),
                *changed_rules(),
                *rules,
            )
        )

        goal_map = EngineInitializer._make_goal_map_from_rules(rules)

        def ensure_absolute_path(v: str) -> str:
            return Path(v).resolve().as_posix()

        scheduler = Scheduler(
            native=native,
            ignore_patterns=pants_ignore_patterns,
            use_gitignore=use_gitignore,
            build_root=build_root,
            local_store_dir=ensure_absolute_path(local_store_dir),
            local_execution_root_dir=ensure_absolute_path(local_execution_root_dir),
            named_caches_dir=ensure_absolute_path(named_caches_dir),
            rules=rules,
            union_membership=union_membership,
            execution_options=execution_options,
            include_trace_on_error=include_trace_on_error,
            visualize_to_dir=bootstrap_options.native_engine_visualize_to,
        )

        return GraphScheduler(scheduler, goal_map)
