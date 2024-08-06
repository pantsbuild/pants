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
from pants.option.scope import ScopeInfo


@dataclass
class AuxiliaryGoalContext:
    """Context passed to a `AuxiliaryGoal.run` implementation."""

    build_config: BuildConfiguration
    graph_session: GraphSession
    options: Options
    specs: Specs
    union_membership: UnionMembership


class AuxiliaryGoal(ABC, GoalSubsystem):
    """Configure an "auxiliary" goal which allows rules to "take over" Pants client execution in
    lieu of executing an ordinary goal.

    Only a single auxiliary goal is executed per run, any remaining goals/arguments are passed
    unaltered to the auxiliary goal. Auxiliary goals have precedence over regular goals.

    When multiple auxiliary goals are presented, the first auxiliary goal will be used unless there is a
    auxiliary goal that begin with a hyphen (`-`), in which case the last such "option goal" will be
    prioritized. This is to support things like `./pants some-builtin-goal --help`.

    The intended use for this API is rule code which runs a server (for example, a BSP server)
    which provides an alternate interface to the Pants rule engine, or other kinds of goals
    which must run "outside" of the usual engine processing to function.
    """

    # Used by `pants.option.arg_splitter.ArgSplitter()` to optionally allow aliasing auxiliary goals.
    aliases: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def create_scope_info(cls, **scope_info_kwargs) -> ScopeInfo:
        return super().create_scope_info(is_auxiliary=True, **scope_info_kwargs)

    @abstractmethod
    def run(
        self,
        context: AuxiliaryGoalContext,
    ) -> ExitCode:
        pass
