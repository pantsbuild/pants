# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python.goals.lockfile import (
    AmbiguousResolveNamesError,
    PythonLockfileRequest,
    PythonToolLockfileSentinel,
    UnrecognizedResolveNamesError,
    determine_resolves_to_generate,
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

    all_user_resolves = ["u1", "u2", "u3"]

    def assert_chosen(
        requested: list[str],
        expected_user_resolves: list[str],
        expected_tools: list[type[PythonToolLockfileSentinel]],
    ) -> None:
        user_resolves, tools = determine_resolves_to_generate(
            all_user_resolves, [Tool1, Tool2, Tool3], requested
        )
        assert user_resolves == expected_user_resolves
        assert tools == expected_tools

    assert_chosen(
        [Tool2.options_scope, "u2"], expected_user_resolves=["u2"], expected_tools=[Tool2]
    )
    assert_chosen(
        [Tool1.options_scope, Tool3.options_scope],
        expected_user_resolves=[],
        expected_tools=[Tool1, Tool3],
    )

    # If none are specifically requested, return all.
    assert_chosen(
        [], expected_user_resolves=["u1", "u2", "u3"], expected_tools=[Tool1, Tool2, Tool3]
    )

    with pytest.raises(UnrecognizedResolveNamesError):
        assert_chosen(["fake"], expected_user_resolves=[], expected_tools=[])

    # Error if same resolve name used for tool lockfiles and user lockfiles.
    class AmbiguousTool(PythonToolLockfileSentinel):
        options_scope = "ambiguous"

    with pytest.raises(AmbiguousResolveNamesError):
        determine_resolves_to_generate(
            {"ambiguous": "lockfile.txt"}, [AmbiguousTool], ["ambiguous"]
        )


@pytest.mark.parametrize(
    "unrecognized,bad_entry_str,name_str",
    (
        (["fake"], "fake", "name"),
        (["fake1", "fake2"], "['fake1', 'fake2']", "names"),
    ),
)
def test_unrecognized_resolve_names_error(
    unrecognized: list[str], bad_entry_str: str, name_str: str
) -> None:
    with pytest.raises(UnrecognizedResolveNamesError) as exc:
        raise UnrecognizedResolveNamesError(unrecognized, ["valid1", "valid2", "valid3"])
    assert (
        f"Unrecognized resolve {name_str} from the option `--generate-lockfiles-resolve`: "
        f"{bad_entry_str}\n\nAll valid resolve names: ['valid1', 'valid2', 'valid3']"
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
