# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.python.goals.lockfile import (
    GeneratePythonLockfile,
    RequestedPythonUserResolveNames,
    setup_user_lockfile_requests,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonRequirementTarget
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals.generate_lockfiles import UserGenerateLockfiles
from pants.engine.rules import SubsystemRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, QueryRule, RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


def test_multiple_resolves() -> None:
    rule_runner = RuleRunner(
        rules=[
            setup_user_lockfile_requests,
            SubsystemRule(PythonSetup),
            QueryRule(UserGenerateLockfiles, [RequestedPythonUserResolveNames]),
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
    result = rule_runner.request(
        UserGenerateLockfiles, [RequestedPythonUserResolveNames(["a", "b"])]
    )
    assert set(result) == {
        GeneratePythonLockfile(
            requirements=FrozenOrderedSet(["a", "both1", "both2"]),
            interpreter_constraints=InterpreterConstraints(
                PythonSetup.default_interpreter_constraints
            ),
            resolve_name="a",
            lockfile_dest="a.lock",
        ),
        GeneratePythonLockfile(
            requirements=FrozenOrderedSet(["b", "both1", "both2"]),
            interpreter_constraints=InterpreterConstraints(
                PythonSetup.default_interpreter_constraints
            ),
            resolve_name="b",
            lockfile_dest="b.lock",
        ),
    }
