# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from enum import Enum
from typing import Iterable, Type, TypeVar, Protocol

from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.core.goals.generate_lockfiles import GenerateToolLockfileSentinel
from pants.engine.rules import rule
from pants.engine.unions import UnionRule
from pants.util.memo import memoized


class PythonToolBase(Protocol):
    """Projection of necessary fields, avoids import cycle"""
    options_scope: str


@memoized
def _pex_simple_lockfile_rules(python_tool: Type[PythonToolBase]) -> Iterable:
    class SimplePexLockfileSentinel(GenerateToolLockfileSentinel):
        resolve_name = python_tool.options_scope

    @rule(_param_type_overrides={"request": SimplePexLockfileSentinel, "tool": python_tool})
    async def lockfile_generator(
        request: GenerateToolLockfileSentinel,
        tool: PythonToolBase,
    ) -> GeneratePythonLockfile:
        return GeneratePythonLockfile.from_tool(tool)

    return (
        UnionRule(GenerateToolLockfileSentinel, SimplePexLockfileSentinel),
        lockfile_generator,
    )


class LockfileRules(Enum):
    """The type of lockfile generation strategy to use for a tool.

    - NONE : Does not import Python lockfile rules
    - CUSTOM : Only Python lockfile rules are added, the rest are implemented by the tool
    - PYTHON : A tool that can be installed with pip simply with `pip install mytool`.
        It does not need other information about the code it operates on
    """

    NONE = "none"
    CUSTOM = "custom"
    PYTHON = "python"

    def default_rules(self, cls) -> Iterable:
        if self == LockfileRules.NONE:
            return

        yield from lockfile.rules()

        if self == LockfileRules.PYTHON:
            yield from _pex_simple_lockfile_rules(cls)
