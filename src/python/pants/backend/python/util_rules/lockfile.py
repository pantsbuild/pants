# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable, Type

from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import (
    LockfileRules,
    PythonToolRequirementsBase,
)
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import rule
from pants.engine.unions import UnionRule
from pants.util.memo import memoized


@memoized
def _pex_simple_lockfile_rules(python_tool: Type["PythonToolRequirementsBase"]) -> Iterable:
    class SimplePexLockfileSentinel(GenerateToolLockfileSentinel):
        resolve_name = python_tool.options_scope

    SimplePexLockfileSentinel.__name__ = f"{python_tool.__name__}LockfileSentinel"
    SimplePexLockfileSentinel.__qualname__ = f"{__name__}.{python_tool.__name__}LockfileSentinel"

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


def default_rules(cls: Type[PythonToolRequirementsBase]) -> Iterable:
    if cls.lockfile_rules_type == LockfileRules.SIMPLE:
        yield from _pex_simple_lockfile_rules(cls)
    else:
        return
