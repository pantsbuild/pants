# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Iterable, Type

from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import rule
from pants.engine.unions import UnionRule
from pants.util.memo import memoized

if TYPE_CHECKING:
    from pants.backend.python.subsystems.python_tool_base import PythonToolRequirementsBase


@memoized
def _pex_simple_lockfile_rules(python_tool: Type["PythonToolRequirementsBase"]) -> Iterable:
    class SimplePexLockfileSentinel(GenerateToolLockfileSentinel):
        resolve_name = python_tool.options_scope

    @rule(_param_type_overrides={"request": SimplePexLockfileSentinel, "tool": python_tool})
    async def lockfile_generator(
        request: GenerateToolLockfileSentinel,
        tool: "PythonToolRequirementsBase",
    ) -> GeneratePythonLockfile:
        return GeneratePythonLockfile.from_tool(tool)

    return (
        UnionRule(GenerateToolLockfileSentinel, SimplePexLockfileSentinel),
        lockfile_generator,
    )


class LockfileRules(Enum):
    """The type of lockfile generation strategy to use for a tool.

    - CUSTOM : Only Python lockfile rules are added, the rest are implemented by the tool
    - SIMPLE : A python tool that can be installed with pip simply with `pip install mytool`.
        It does not need other information about the code it operates on, such as their interpreter constraints.
    """

    CUSTOM = "custom"
    SIMPLE = "simple"

    def default_rules(self, cls) -> Iterable:
        if self == LockfileRules.SIMPLE:
            yield from _pex_simple_lockfile_rules(cls)
        else:
            return
