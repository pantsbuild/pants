# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pants.base.exiter import ExitCode
from pants.base.specs import Specs
from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.goal import GoalSubsystem
from pants.engine.unions import UnionMembership
from pants.init.engine_initializer import GraphSession
from pants.option.options import Options
from pants.option.scope import ScopeInfo


class BuiltinGoal(ABC, GoalSubsystem):
    """Builtin goals have precedence over regular goal rules.

    Only a single builtin goal is executed per run, any remaining goals/arguments are passed
    unaltered to the builtin goal.

    When multiple builtin goals are presented, the first builtin goal will be used unless there is a
    builtin goal that begin with a hyphen (`-`), in which case the last such "option goal" will be
    prioritized. This is to support things like `./pants some-builtin-goal --help`.
    """

    # Used by `pants.option.arg_splitter.ArgSplitter()` to optionally allow aliasing builtin goals.
    aliases: ClassVar[tuple[str, ...]] = ()

    @classmethod
    def create_scope_info(cls, **scope_info_kwargs) -> ScopeInfo:
        return super().create_scope_info(is_builtin=True, **scope_info_kwargs)

    @abstractmethod
    def run(
        self,
        *,
        build_config: BuildConfiguration,
        graph_session: GraphSession,
        options: Options,
        specs: Specs,
        union_membership: UnionMembership,
    ) -> ExitCode:
        pass
