# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partial
from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.project_info.dependencies import Dependencies, rules
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourcesGeneratorTarget
from pants.engine.target import SpecialCasedDependencies, Target
from pants.testutil.rule_runner import RuleRunner


# We verify that any subclasses of `SpecialCasedDependencies` will show up with the `dependencies`
# goal by creating a mock target.
class SpecialDepsField(SpecialCasedDependencies):
    alias = "special_deps"


class SpecialDepsTarget(Target):
    alias = "special_deps_tgt"
    core_fields = (SpecialDepsField,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=rules(),
        target_types=[PythonSourcesGeneratorTarget, PythonRequirementTarget, SpecialDepsTarget],
    )


def create_python_sources(
    rule_runner: RuleRunner, path: str, *, dependencies: Optional[List[str]] = None
) -> None:
    rule_runner.write_files(
        {path: f"python_sources(name='target', sources=[], dependencies={dependencies or []})"}
    )


def create_python_requirement_tgts(rule_runner: RuleRunner, *names: str) -> None:
    rule_runner.write_files(
        {
            "3rdparty/python/BUILD": "\n".join(
                dedent(
                    f"""\
                    python_requirement(
                        name='{name}',
                        requirements=['{name}==1.0.0'],
                    )
                    """
                )
                for name in names
            )
        }
    )


def assert_dependencies(
    rule_runner: RuleRunner,
    *,
    specs: List[str],
    expected: List[str],
    transitive: bool = False,
    closed: bool = False,
) -> None:
    args = []
    if transitive:
        args.append("--transitive")
    if closed:
        args.append("--closed")
    result = rule_runner.run_goal_rule(Dependencies, args=[*args, *specs])
    assert result.stdout.splitlines() == expected


def test_no_target(rule_runner: RuleRunner) -> None:
    assert_dependencies(rule_runner, specs=[], expected=[])
    assert_dependencies(rule_runner, specs=[], expected=[], transitive=True)


def test_no_dependencies(rule_runner: RuleRunner) -> None:
    create_python_sources(rule_runner, path="some/target/BUILD")
    assert_dependencies(rule_runner, specs=["some/target"], expected=[])
    assert_dependencies(rule_runner, specs=["some/target"], expected=[], transitive=True)
    assert_dependencies(
        rule_runner, specs=["some/target"], expected=["some/target:target"], closed=True
    )
    assert_dependencies(
        rule_runner,
        specs=["some/target"],
        expected=["some/target:target"],
        transitive=True,
        closed=True,
    )


def test_special_cased_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                special_deps_tgt(name='t1')
                special_deps_tgt(name='t2', special_deps=[':t1'])
                special_deps_tgt(name='t3', special_deps=[':t2'])
                """
            ),
        }
    )
    assert_dependencies(rule_runner, specs=["//:t3"], expected=["//:t2"])
    assert_dependencies(rule_runner, specs=["//:t3"], expected=["//:t1", "//:t2"], transitive=True)


def test_python_dependencies(rule_runner: RuleRunner) -> None:
    create_python_requirement_tgts(rule_runner, "req1", "req2")
    create_python_sources(rule_runner, path="dep/target/BUILD")
    create_python_sources(
        rule_runner, path="some/target/BUILD", dependencies=["dep/target", "3rdparty/python:req1"]
    )
    create_python_sources(
        rule_runner,
        path="some/other/target/BUILD",
        dependencies=["some/target", "3rdparty/python:req2"],
    )

    assert_deps = partial(assert_dependencies, rule_runner)

    assert_deps(
        specs=["some/other/target"],
        transitive=False,
        expected=["3rdparty/python:req2", "some/target:target"],
    )
    assert_deps(
        specs=["some/other/target"],
        transitive=True,
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target:target",
            "some/target:target",
        ],
    )

    # Glob the whole repo. `some/other/target` should not be included if --closed is not set,
    # because nothing depends on it.
    assert_deps(
        specs=["::"],
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target:target",
            "some/target:target",
        ],
    )
    assert_deps(
        specs=["::"],
        transitive=True,
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target:target",
            "some/target:target",
        ],
    )
    assert_deps(
        specs=["::"],
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target:target",
            "some/other/target:target",
            "some/target:target",
        ],
        closed=True,
    )
    assert_deps(
        specs=["::"],
        transitive=True,
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target:target",
            "some/other/target:target",
            "some/target:target",
        ],
        closed=True,
    )
