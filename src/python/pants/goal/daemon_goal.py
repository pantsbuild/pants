# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.goal import GoalSubsystem
from pants.engine.unions import UnionMembership
from pants.init.engine_initializer import GraphSession
from pants.option.options import Options


@dataclass
class DaemonGoalContext:
    """Context passed to a `DaemonGoal.run` implementation."""
    build_config: BuildConfiguration
    graph_session: GraphSession
    options: Options
    specs: Specs
    union_membership: UnionMembership
    

class DaemonGoal(ABC, GoalSubsystem):
    """Configure a "daemon" goal which allows rules to "take over" Pants client execution.

    Only a single daemon goal is executed per run, any remaining goals/arguments are passed
    unaltered to the builtin goal. Daemon goals have precedence over regular goals.

    When multiple daemon goals are presented, the first builtin goal will be used unless there is a
    daemon goal that begin with a hyphen (`-`), in which case the last such "option goal" will be
    prioritized. This is to support things like `./pants some-builtin-goal --help`.
    """

    # Used by `pants.option.arg_splitter.ArgSplitter()` to optionally allow aliasing builtin goals.
    aliases: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def create_scope_info(cls, **scope_info_kwargs) -> ScopeInfo:
        return super().create_scope_info(is_daemon=True, **scope_info_kwargs)

    @abstractmethod
    def run(
        self,
        context: DaemonGoalContext,
    ) -> ExitCode:
        pass
