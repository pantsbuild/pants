# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import Iterable, Type

from typing_extensions import Protocol

from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import rule
from pants.engine.unions import UnionRule
from pants.util.memo import memoized


class LockfileRules(Enum):
    """The type of lockfile generation strategy to use for a tool.

    - CUSTOM : Only Python lockfile rules are added, the rest are implemented by the tool
    - SIMPLE : A python tool that can be installed with pip simply with `pip install mytool`.
        It does not need other information about the code it operates on, such as their interpreter constraints.
    """

    CUSTOM = "custom"
    SIMPLE = "simple"


class LockfileRequestable(Protocol):
    options_scope: str
    lockfile_rules_type: LockfileRules

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


def default_rules(cls: Type[LockfileRequestable]) -> Iterable:
    if cls.lockfile_rules_type == LockfileRules.SIMPLE:
        yield from _pex_simple_lockfile_rules(cls)
    elif cls.lockfile_rules_type == LockfileRules.CUSTOM:
        return
    else:
        raise NotImplementedError(
            f"Lockfile rule generator of type {cls.lockfile_rules_type} is missing default rules!"
        )
