# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.goals.lockfile import (
    PythonLockfileRequest,
    UnrecognizedResolveNamesError,
    determine_resolves_to_generate,
)
from pants.backend.python.subsystems.python_tool_base import DEFAULT_TOOL_LOCKFILE, NO_TOOL_LOCKFILE
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.util.ordered_set import FrozenOrderedSet


def test_determine_resolves_to_generate(caplog) -> None:
    def create_request(name: str, lockfile_dest: str | None = None) -> PythonLockfileRequest:
        return PythonLockfileRequest(
            FrozenOrderedSet(),
            InterpreterConstraints(),
            resolve_name=name,
            lockfile_dest=lockfile_dest or f"{name}.txt",
        )

    tool1 = create_request("tool1")
    tool2 = create_request("tool2")
    tool3 = create_request("tool3")
    disabled_tool = create_request("none", lockfile_dest=NO_TOOL_LOCKFILE)
    default_tool = create_request("default", lockfile_dest=DEFAULT_TOOL_LOCKFILE)

    def assert_chosen(requested: list[str], expected: list[PythonLockfileRequest]) -> None:
        assert (
            determine_resolves_to_generate(
                [tool1, tool2, tool3, disabled_tool, default_tool], requested
            )
            == expected
        )

    assert_chosen([tool2.resolve_name], [tool2])
    assert_chosen([tool1.resolve_name, tool3.resolve_name], [tool1, tool3])

    # If none are specifically requested, return all valid.
    assert_chosen([], [tool1, tool2, tool3])

    with pytest.raises(UnrecognizedResolveNamesError) as exc:
        assert_chosen(["fake"], [])
    assert (
        "Unrecognized resolve name from the option `[generate-lockfiles].resolves`: fake\n\n"
        "All valid resolve names: ['default', 'none', 'tool1', 'tool2', 'tool3']"
    ) in str(exc.value)

    with pytest.raises(UnrecognizedResolveNamesError) as exc:
        assert_chosen(["fake1", "fake2"], [])
    assert (
        "Unrecognized resolve names from the option `[generate-lockfiles].resolves`: "
        "['fake1', 'fake2']"
    ) in str(exc.value)

    # Warn if requested tool is set to disabled or default.
    assert_chosen([disabled_tool.resolve_name], [])
    assert len(caplog.records) == 1
    assert (
        f"`[{disabled_tool.resolve_name}].lockfile` is set to `{NO_TOOL_LOCKFILE}`" in caplog.text
    )
    caplog.clear()

    assert_chosen([default_tool.resolve_name], [])
    assert len(caplog.records) == 1
    assert (
        f"`[{default_tool.resolve_name}].lockfile` is set to `{DEFAULT_TOOL_LOCKFILE}`"
        in caplog.text
    )
    caplog.clear()
