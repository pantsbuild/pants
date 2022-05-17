# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Iterable, cast

from pants.base.build_environment import get_buildroot
from pants.base.build_root import BuildRoot
from pants.base.exiter import PANTS_SUCCEEDED_EXIT_CODE
from pants.base.specs import Specs
from pants.bsp.protocol import BSPHandlerMapping
from pants.build_graph.build_configuration import BuildConfiguration
from pants.core.util_rules import system_binaries
from pants.engine import desktop, environment, fs, platform, process
from pants.engine.console import Console
from pants.engine.fs import PathGlobs, Snapshot, Workspace
from pants.engine.goal import Goal
from pants.engine.internals import build_files, graph, options_parsing
from pants.engine.internals.native_engine import PyExecutor, PySessionCancellationLatch
from pants.engine.internals.parser import Parser
from pants.engine.internals.scheduler import Scheduler, SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.internals.session import SessionValues
from pants.engine.rules import QueryRule, collect_rules, rule
from pants.engine.streaming_workunit_handler import rules as streaming_workunit_handler_rules
from pants.engine.target import RegisteredTargetTypes
from pants.engine.unions import UnionMembership, UnionRule
from pants.init import specs_calculator
from pants.option.global_options import (
    DEFAULT_EXECUTION_OPTIONS,
    DynamicRemoteOptions,
    ExecutionOptions,
    GlobalOptions,
    LocalStoreOptions,
)
from pants.option.option_value_container import OptionValueContainer
from pants.option.subsystem import Subsystem
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet
from pants.vcs.changed import rules as changed_rules
from pants.vcs.git import rules as git_rules

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphScheduler:
    """A thin wrapper around a Scheduler configured with @rules."""

    scheduler: Scheduler
    goal_map: Any

    def new_session(
        self,
        build_id,
        dynamic_ui: bool = False,
        ui_use_prodash: bool = False,
        use_colors=True,
        max_workunit_level: LogLevel = LogLevel.DEBUG,
        session_values: SessionValues | None = None,
        cancellation_latch: PySessionCancellationLatch | None = None,
    ) -> GraphSession:
        session = self.scheduler.new_session(
            build_id,
            dynamic_ui,
            ui_use_prodash,
            max_workunit_level=max_workunit_level,
            session_values=session_values,
            cancellation_latch=cancellation_latch,
        )
        console = Console(use_colors=use_colors, session=session if dynamic_ui else None)
        return GraphSession(session, console, self.goal_map)


@dataclass(frozen=True)
class GraphSession:
    """A thin wrapper around a SchedulerSession configured with @rules."""

    scheduler_session: SchedulerSession
    console: Console
    goal_map: Any

    # NB: Keep this in sync with the method `run_goal_rules`.
    goal_param_types: ClassVar[tuple[type, ...]] = (Specs, Console, Workspace)

    def goal_consumed_subsystem_scopes(self, goal_name: str) -> tuple[str, ...]:
        """Return the scopes of subsystems that could be consumed while running the given goal."""
        goal_product = self.goal_map.get(goal_name)
        if not goal_product:
            return tuple()
        consumed_types = self.goal_consumed_types(goal_product)
        return tuple(
            sorted({typ.options_scope for typ in consumed_types if issubclass(typ, Subsystem)})
        )

    def goal_consumed_types(self, goal_product: type) -> set[type]:
        """Return the set of types that could possibly be consumed while running the given goal."""
        return set(
            self.scheduler_session.scheduler.rule_graph_consumed_types(
                self.goal_param_types, goal_product
            )
        )

    def run_goal_rules(
        self,
        *,
        union_membership: UnionMembership,
        goals: Iterable[str],
        specs: Specs,
        poll: bool = False,
        poll_delay: float | None = None,
    ) -> int:
        """Runs @goal_rules sequentially and interactively by requesting their implicit Goal
        products.

        For retryable failures, raises scheduler.ExecutionError.

        :returns: An exit code.
        """

        workspace = Workspace(self.scheduler_session)

        for goal in goals:
            goal_product = self.goal_map[goal]
            # NB: We no-op for goals that have no implementation because no relevant backends are
            # registered. We might want to reconsider the behavior to instead warn or error when
            # trying to run something like `./pants run` without any backends registered.
            if not goal_product.subsystem_cls.activated(union_membership):
                continue
            # NB: Keep this in sync with the property `goal_param_types`.
            params = Params(specs, self.console, workspace)
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
            deprecated_goal = r.output_type.subsystem_cls.deprecated_options_scope
            for goal_name in [goal, deprecated_goal] if deprecated_goal else [goal]:
                if goal_name in goal_map:
                    raise EngineInitializer.GoalMappingError(
                        f"could not map goal `{goal_name}` to rule `{r}`: already claimed by product "
                        f"`{goal_map[goal_name]}`"
                    )
                goal_map[goal_name] = r.output_type
        return goal_map

    @staticmethod
    def setup_graph(
        bootstrap_options: OptionValueContainer,
        build_configuration: BuildConfiguration,
        dynamic_remote_options: DynamicRemoteOptions,
        executor: PyExecutor | None = None,
    ) -> GraphScheduler:
        build_root = get_buildroot()
        executor = executor or GlobalOptions.create_py_executor(bootstrap_options)
        execution_options = ExecutionOptions.from_options(bootstrap_options, dynamic_remote_options)
        local_store_options = LocalStoreOptions.from_options(bootstrap_options)
        return EngineInitializer.setup_graph_extended(
            build_configuration,
            execution_options,
            executor=executor,
            pants_ignore_patterns=GlobalOptions.compute_pants_ignore(build_root, bootstrap_options),
            use_gitignore=bootstrap_options.pants_ignore_use_gitignore,
            local_store_options=local_store_options,
            local_execution_root_dir=bootstrap_options.local_execution_root_dir,
            named_caches_dir=bootstrap_options.named_caches_dir,
            ca_certs_path=bootstrap_options.ca_certs_path,
            build_root=build_root,
            include_trace_on_error=bootstrap_options.print_stacktrace,
            engine_visualize_to=bootstrap_options.engine_visualize_to,
            watch_filesystem=bootstrap_options.watch_filesystem,
        )

    @staticmethod
    def setup_graph_extended(
        build_configuration: BuildConfiguration,
        execution_options: ExecutionOptions,
        *,
        executor: PyExecutor,
        pants_ignore_patterns: list[str],
        use_gitignore: bool,
        local_store_options: LocalStoreOptions,
        local_execution_root_dir: str,
        named_caches_dir: str,
        ca_certs_path: str | None = None,
        build_root: str | None = None,
        include_trace_on_error: bool = True,
        engine_visualize_to: str | None = None,
        watch_filesystem: bool = True,
    ) -> GraphScheduler:
        build_root_path = build_root or get_buildroot()

        rules = build_configuration.rules
        union_membership: UnionMembership
        registered_target_types = RegisteredTargetTypes.create(build_configuration.target_types)

        execution_options = execution_options or DEFAULT_EXECUTION_OPTIONS

        @rule
        def parser_singleton() -> Parser:
            return Parser(
                build_root=build_root_path,
                target_type_aliases=registered_target_types.aliases,
                object_aliases=build_configuration.registered_aliases,
            )

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
                *build_files.rules(),
                *fs.rules(),
                *environment.rules(),
                *desktop.rules(),
                *git_rules(),
                *graph.rules(),
                *options_parsing.rules(),
                *process.rules(),
                *system_binaries.rules(),
                *platform.rules(),
                *changed_rules(),
                *streaming_workunit_handler_rules(),
                *specs_calculator.rules(),
                *rules,
            )
        )

        goal_map = EngineInitializer._make_goal_map_from_rules(rules)

        union_membership = UnionMembership.from_rules(
            (
                *build_configuration.union_rules,
                *(r for r in rules if isinstance(r, UnionRule)),
            )
        )

        rules = FrozenOrderedSet(
            (
                *rules,
                # Install queries for each Goal.
                *(
                    QueryRule(goal_type, GraphSession.goal_param_types)
                    for goal_type in goal_map.values()
                ),
                # Install queries for each request/response pair used by the BSP support.
                # Note: These are necessary because the BSP support is a built-in goal that makes
                # synchronous requests into the engine.
                *(
                    QueryRule(impl.response_type, (impl.request_type, Workspace))
                    for impl in union_membership.get(BSPHandlerMapping)
                ),
                QueryRule(Snapshot, [PathGlobs]),  # Used by the SchedulerService.
            )
        )

        def ensure_absolute_path(v: str) -> str:
            return Path(v).resolve().as_posix()

        def ensure_optional_absolute_path(v: str | None) -> str | None:
            if v is None:
                return None
            return ensure_absolute_path(v)

        scheduler = Scheduler(
            ignore_patterns=pants_ignore_patterns,
            use_gitignore=use_gitignore,
            build_root=build_root_path,
            local_execution_root_dir=ensure_absolute_path(local_execution_root_dir),
            named_caches_dir=ensure_absolute_path(named_caches_dir),
            ca_certs_path=ensure_optional_absolute_path(ca_certs_path),
            rules=rules,
            union_membership=union_membership,
            executor=executor,
            execution_options=execution_options,
            local_store_options=local_store_options,
            include_trace_on_error=include_trace_on_error,
            visualize_to_dir=engine_visualize_to,
            watch_filesystem=watch_filesystem,
        )

        return GraphScheduler(scheduler, goal_map)
