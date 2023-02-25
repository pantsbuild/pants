# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import Iterable, Protocol, Type

from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import (
    LockfileRules,
    PythonToolRequirementsBase,
)
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import rule
from pants.engine.unions import UnionRule
from pants.util.memo import memoized


class LockfileRequestable(Protocol):
    options_scope: str

    def to_lockfile_request(
        self,
        interpreter_constraints: InterpreterConstraints | None = None,
        extra_requirements: Iterable[str] = (),
    ) -> GeneratePythonLockfile:
        ...


@memoized
def _pex_simple_lockfile_rules(python_tool: Type[LockfileRequestable]) -> Iterable:
    class SimplePexLockfileSentinel(GenerateToolLockfileSentinel):
        resolve_name = python_tool.options_scope

    SimplePexLockfileSentinel.__name__ = f"{python_tool.__name__}LockfileSentinel"
    SimplePexLockfileSentinel.__qualname__ = f"{__name__}.{python_tool.__name__}LockfileSentinel"

    @rule(_param_type_overrides={"request": SimplePexLockfileSentinel, "tool": python_tool})
    async def lockfile_generator(
        request: GenerateToolLockfileSentinel,
        tool: LockfileRequestable,
    ) -> GeneratePythonLockfile:
        return tool.to_lockfile_request()

    return (
        UnionRule(GenerateToolLockfileSentinel, SimplePexLockfileSentinel),
        lockfile_generator,
    )


def default_rules(cls: Type[PythonToolRequirementsBase]) -> Iterable:
    if cls.lockfile_rules_type == LockfileRules.SIMPLE:
        yield from _pex_simple_lockfile_rules(cls)
    else:
        return
