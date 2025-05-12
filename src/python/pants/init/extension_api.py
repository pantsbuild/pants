# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Protocol

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.engine.rules import Rule
from pants.engine.target import Target
from pants.engine.unions import UnionRule
from pants.goal.auxiliary_goal import AuxiliaryGoal
from pants.option.subsystem import Subsystem


class ExtensionInitContextV0(Protocol):
    """A context object used by extension initializers to register their capabilities with the
    engine."""

    def register_aliases(self, aliases: BuildFileAliases) -> None: ...

    def register_auxiliary_goals(self, goals: Iterable[type[AuxiliaryGoal]]) -> None: ...

    def register_remote_auth_plugin(self, remote_auth_plugin: Callable) -> None: ...

    def register_rules(self, rules: Iterable[Rule | UnionRule]) -> None: ...

    def register_subsystems(self, subsystems: Iterable[type[Subsystem]]): ...

    def register_target_types(self, target_types: Iterable[type[Target]] | Any) -> None: ...
