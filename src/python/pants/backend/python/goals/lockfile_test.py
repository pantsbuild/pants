# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.goals.lockfile import (
    AmbiguousResolveNamesError,
    PythonLockfileRequest,
    _SpecifiedUserResolves,
    _UserLockfileRequests,
    determine_resolves_to_generate,
    filter_tool_lockfile_requests,
    setup_user_lockfile_requests,
)
from pants.backend.python.subsystems.python_tool_base import DEFAULT_TOOL_LOCKFILE, NO_TOOL_LOCKFILE
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementTarget, UnrecognizedResolveNamesError
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import (
    LockfileRequest,
    ToolLockfileSentinel,
    WrappedLockfileRequest,
)
from pants.engine.rules import SubsystemRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


def test_determine_tool_sentinels_to_generate() -> None:
    class Tool1(ToolLockfileSentinel):
        options_scope = "tool1"

    class Tool2(ToolLockfileSentinel):
        options_scope = "tool2"

    class Tool3(ToolLockfileSentinel):
        options_scope = "tool3"

    all_user_resolves = ["u1", "u2", "u3"]

    def assert_chosen(
        requested: list[str],
        expected_user_resolves: list[str],
        expected_tools: list[type[ToolLockfileSentinel]],
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
    class AmbiguousTool(ToolLockfileSentinel):
        options_scope = "ambiguous"

    with pytest.raises(AmbiguousResolveNamesError):
        determine_resolves_to_generate(
            {"ambiguous": "lockfile.txt"}, [AmbiguousTool], ["ambiguous"]
        )


def test_filter_tool_lockfile_requests() -> None:
    def create_request(name: str, lockfile_dest: str | None = None) -> LockfileRequest:
        return LockfileRequest(resolve_name=name, lockfile_dest=lockfile_dest or f"{name}.txt")

    tool1 = create_request("tool1")
    tool2 = create_request("tool2")
    disabled_tool = create_request("none", lockfile_dest=NO_TOOL_LOCKFILE)
    default_tool = create_request("default", lockfile_dest=DEFAULT_TOOL_LOCKFILE)

    def assert_filtered(
        extra_request: LockfileRequest | None,
        *,
        resolve_specified: bool,
    ) -> None:
        requests = [WrappedLockfileRequest(tool1), WrappedLockfileRequest(tool2)]
        if extra_request:
            requests.append(WrappedLockfileRequest(extra_request))
        assert filter_tool_lockfile_requests(requests, resolve_specified=resolve_specified) == [
            tool1,
            tool2,
        ]

    assert_filtered(None, resolve_specified=False)
    assert_filtered(None, resolve_specified=True)

    assert_filtered(disabled_tool, resolve_specified=False)
    with pytest.raises(ValueError) as exc:
        assert_filtered(disabled_tool, resolve_specified=True)
    assert f"`[{disabled_tool.resolve_name}].lockfile` is set to `{NO_TOOL_LOCKFILE}`" in str(
        exc.value
    )

    assert_filtered(default_tool, resolve_specified=False)
    with pytest.raises(ValueError) as exc:
        assert_filtered(default_tool, resolve_specified=True)
    assert f"`[{default_tool.resolve_name}].lockfile` is set to `{DEFAULT_TOOL_LOCKFILE}`" in str(
        exc.value
    )


def test_multiple_resolves() -> None:
    rule_runner = RuleRunner(
        rules=[
            setup_user_lockfile_requests,
            SubsystemRule(PythonSetup),
            QueryRule(_UserLockfileRequests, [_SpecifiedUserResolves]),
        ],
        target_types=[PythonRequirementTarget],
    )
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(
                    name='both',
                    requirements=['both1', 'both2'],
                    experimental_compatible_resolves=['a', 'b'],
                )
                python_requirement(
                    name='a',
                    requirements=['a'],
                    experimental_compatible_resolves=['a'],
                )
                python_requirement(
                    name='b',
                    requirements=['b'],
                    experimental_compatible_resolves=['b'],
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--python-experimental-resolves={'a': 'a.lock', 'b': 'b.lock'}",
            "--python-enable-resolves",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )
    result = rule_runner.request(_UserLockfileRequests, [_SpecifiedUserResolves(["a", "b"])])
    assert set(result) == {
        PythonLockfileRequest(
            requirements=FrozenOrderedSet(["a", "both1", "both2"]),
            interpreter_constraints=InterpreterConstraints(
                PythonSetup.default_interpreter_constraints
            ),
            resolve_name="a",
            lockfile_dest="a.lock",
        ),
        PythonLockfileRequest(
            requirements=FrozenOrderedSet(["b", "both1", "both2"]),
            interpreter_constraints=InterpreterConstraints(
                PythonSetup.default_interpreter_constraints
            ),
            resolve_name="b",
            lockfile_dest="b.lock",
        ),
    }
