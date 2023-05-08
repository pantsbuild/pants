# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable, Type

import pytest

from pants.backend.python.dependency_inference.rules import import_rules
from pants.backend.python.goals import lockfile
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.subsystems.python_tool_base import LockfileRules, PythonToolBase
from pants.backend.python.target_types import ConsoleScript
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.core.goals import generate_lockfiles
from pants.core.goals.generate_lockfiles import GenerateLockfilesGoal, GenerateToolLockfileSentinel
from pants.engine.rules import QueryRule
from pants.engine.target import Dependencies, SingleSourceField, Target
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


def _get_generated_lockfile_sentinel(
    rules: Iterable, subsystem: Type[PythonToolBase]
) -> Type[GenerateToolLockfileSentinel]:
    """Fish the generated lockfile sentinel out of the pool of rules so it can be used in a
    QueryRule."""
    return next(
        r
        for r in rules
        if isinstance(r, UnionRule)
        and r.union_base == GenerateToolLockfileSentinel
        and issubclass(r.union_member, GenerateToolLockfileSentinel)
        and r.union_member.resolve_name == subsystem.options_scope
    ).union_member


class FakeToolWithSimpleLocking(PythonToolBase):
    options_scope = "cowsay"
    name = "Cowsay"
    help = "A tool to test pants"

    default_version = "cowsay==5.0"
    default_main = ConsoleScript("cowsay")

    register_interpreter_constraints = True
    default_interpreter_constraints = ["CPython>=3.7,<4"]

    default_lockfile_resource = ("", "cowsay.lock")
    lockfile_rules_type = LockfileRules.SIMPLE


class MockSourceField(SingleSourceField):
    pass


class MockDependencies(Dependencies):
    pass


class MockTarget(Target):
    alias = "tgt"
    core_fields = (MockSourceField, MockDependencies)


@pytest.fixture
def rule_runner() -> RuleRunner:
    lockfile_sentinel = _get_generated_lockfile_sentinel(
        FakeToolWithSimpleLocking.rules(), FakeToolWithSimpleLocking
    )
    rule_runner = RuleRunner(
        rules=[
            *lockfile.rules(),
            *generate_lockfiles.rules(),
            *import_rules(),
            *FakeToolWithSimpleLocking.rules(),
            QueryRule(GeneratePythonLockfile, [lockfile_sentinel]),
        ],
        target_types=[MockTarget],
    )

    rule_runner.write_files(
        {"project/example.ext": "", "project/BUILD": "tgt(source='example.ext')"}
    )
    return rule_runner


def test_simple_python_lockfile(rule_runner):
    """Test that the `LockfileType.PEX_SIMPLE` resolved the graph and generates the lockfile."""
    result = rule_runner.run_goal_rule(
        GenerateLockfilesGoal,
        args=[
            "--resolve=cowsay",
            "--cowsay-lockfile=aaa.lock",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    assert result
    lockfile_content = rule_runner.read_file("aaa.lock")
    assert (
        dedent(
            f"""\
             //   "generated_with_requirements": [
             //     "{FakeToolWithSimpleLocking.default_version}"
             //   ],
             """
        )
        in lockfile_content
    )


def test_setup_lockfile(rule_runner) -> None:
    global_constraint = "CPython<4,>=3.8"

    lockfile_sentinel = _get_generated_lockfile_sentinel(
        FakeToolWithSimpleLocking.rules(), FakeToolWithSimpleLocking
    )

    def assert_lockfile_request(
        build_file: str,
        expected_ics: list[str],
        *,
        extra_expected_requirements: list[str] | None = None,
        extra_args: list[str] | None = None,
    ) -> None:
        rule_runner.write_files({"project/BUILD": build_file, "project/f.py": ""})
        rule_runner.set_options(
            ["--cowsay-lockfile=lockfile.txt", *(extra_args or [])],
            env={"PANTS_PYTHON_INTERPRETER_CONSTRAINTS": f"['{global_constraint}']"},
            env_inherit={"PATH", "PYENV_ROOT", "HOME"},
        )
        lockfile_request = rule_runner.request(GeneratePythonLockfile, [lockfile_sentinel()])
        assert lockfile_request.interpreter_constraints == InterpreterConstraints(expected_ics)
        assert lockfile_request.requirements == FrozenOrderedSet(
            [
                FakeToolWithSimpleLocking.default_version,
                *FakeToolWithSimpleLocking.default_extra_requirements,
                *(extra_expected_requirements or ()),
            ]
        )

    assert_lockfile_request(
        "python_sources()", FakeToolWithSimpleLocking.default_interpreter_constraints
    )
    assert_lockfile_request("target()", FakeToolWithSimpleLocking.default_interpreter_constraints)
    # Since the SIMPLE locking mechanism doesn't look at ICs, this will still use tool ICs.
    assert_lockfile_request(
        "python_sources(interpreter_constraints=['CPython<4,>=3.7'])",
        FakeToolWithSimpleLocking.default_interpreter_constraints,
    )
