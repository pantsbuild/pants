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
class AuxillaryGoalContext:
    """Context passed to a `AuxillaryGoal.run` implementation."""

    build_config: BuildConfiguration
    graph_session: GraphSession
    options: Options
    specs: Specs
    union_membership: UnionMembership


class AuxillaryGoal(ABC, GoalSubsystem):
    """Configure a "auxillary" goal which allows rules to "take over" Pants client execution in lieu
    of executing an ordnary goal.

    Only a single auxillary goal is executed per run, any remaining goals/arguments are passed
    unaltered to the auxillary goal. Auxillary goals have precedence over regular goals.

    When multiple auxillary goals are presented, the first auxillary goal will be used unless there is a
    auxillary goal that begin with a hyphen (`-`), in which case the last such "option goal" will be
    prioritized. This is to support things like `./pants some-builtin-goal --help`.

    The intended use for this API is rule code which runs a server (for example, a BSP server)
    which provides an alternate interface to the Pants rule engine, or other kinds of goals
    which must run "outside" of the usual engine processing to function.
    """

    # Used by `pants.option.arg_splitter.ArgSplitter()` to optionally allow aliasing daemon goals.
    aliases: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def create_scope_info(cls, **scope_info_kwargs) -> ScopeInfo:
        return super().create_scope_info(is_auxillary=True, **scope_info_kwargs)

    @abstractmethod
    def run(
        self,
        context: AuxillaryGoalContext,
    ) -> ExitCode:
        pass
