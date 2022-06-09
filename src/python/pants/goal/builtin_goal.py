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

    If a builtin goal is invoked, any remaining arguments are passed unaltered to the builtin goal.
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
