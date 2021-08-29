# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.goals.lockfile import (
    PythonLockfileRequest,
    PythonToolLockfileSentinel,
    UnrecognizedResolveNamesError,
    determine_tool_sentinels_to_generate,
    filter_tool_lockfile_requests,
)
from pants.backend.python.subsystems.python_tool_base import DEFAULT_TOOL_LOCKFILE, NO_TOOL_LOCKFILE
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.util.ordered_set import FrozenOrderedSet


def test_determine_tool_sentinels_to_generate() -> None:
    class Tool1(PythonToolLockfileSentinel):
        options_scope = "tool1"

    class Tool2(PythonToolLockfileSentinel):
        options_scope = "tool2"

    class Tool3(PythonToolLockfileSentinel):
        options_scope = "tool3"

    def assert_chosen(
        requested: list[str], expected: list[type[PythonToolLockfileSentinel]]
    ) -> None:
        assert determine_tool_sentinels_to_generate([Tool1, Tool2, Tool3], requested) == expected

    assert_chosen([Tool2.options_scope], [Tool2])
    assert_chosen([Tool1.options_scope, Tool3.options_scope], [Tool1, Tool3])

    # If none are specifically requested, return all.
    assert_chosen([], [Tool1, Tool2, Tool3])

    with pytest.raises(UnrecognizedResolveNamesError) as exc:
        assert_chosen(["fake"], [])
    assert (
        "Unrecognized resolve name from the option `--generate-lockfiles-resolve`: fake\n\n"
        "All valid resolve names: ['tool1', 'tool2', 'tool3']"
    ) in str(exc.value)

    with pytest.raises(UnrecognizedResolveNamesError) as exc:
        assert_chosen(["fake1", "fake2"], [])
    assert (
        "Unrecognized resolve names from the option `--generate-lockfiles-resolve`: "
        "['fake1', 'fake2']"
    ) in str(exc.value)


def test_filter_tool_lockfile_requests(caplog) -> None:
    def create_request(name: str, lockfile_dest: str | None = None) -> PythonLockfileRequest:
        return PythonLockfileRequest(
            FrozenOrderedSet(),
            InterpreterConstraints(),
            resolve_name=name,
            lockfile_dest=lockfile_dest or f"{name}.txt",
        )

    tool1 = create_request("tool1")
    tool2 = create_request("tool2")
    disabled_tool = create_request("none", lockfile_dest=NO_TOOL_LOCKFILE)
    default_tool = create_request("default", lockfile_dest=DEFAULT_TOOL_LOCKFILE)

    def assert_filtered(
        extra_request: PythonLockfileRequest | None,
        *,
        resolve_specified: bool,
        expected_log: str | None,
    ) -> None:
        requests = [tool1, tool2]
        if extra_request:
            requests.append(extra_request)
        assert filter_tool_lockfile_requests(requests, resolve_specified=resolve_specified) == [
            tool1,
            tool2,
        ]
        if expected_log:
            assert len(caplog.records) == 1
            assert expected_log in caplog.text
        else:
            assert not caplog.records
        caplog.clear()

    assert_filtered(None, resolve_specified=False, expected_log=None)
    assert_filtered(None, resolve_specified=True, expected_log=None)

    assert_filtered(disabled_tool, resolve_specified=False, expected_log=None)
    assert_filtered(
        disabled_tool,
        resolve_specified=True,
        expected_log=f"`[{disabled_tool.resolve_name}].lockfile` is set to `{NO_TOOL_LOCKFILE}`",
    )

    assert_filtered(default_tool, resolve_specified=False, expected_log=None)
    assert_filtered(
        default_tool,
        resolve_specified=True,
        expected_log=(
            f"`[{default_tool.resolve_name}].lockfile` is set to `{DEFAULT_TOOL_LOCKFILE}`"
        ),
    )
