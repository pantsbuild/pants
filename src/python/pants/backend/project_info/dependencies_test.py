# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from functools import partial
from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.project_info.dependencies import Dependencies
from pants.backend.project_info.dependencies import DependenciesOutputFormat as OutputFormat
from pants.backend.project_info.dependencies import DependencyType, rules
from pants.backend.python.target_types import PythonLibrary, PythonRequirementLibrary
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
        rules=rules(), target_types=[PythonLibrary, PythonRequirementLibrary, SpecialDepsTarget]
    )


def create_python_library(
    rule_runner: RuleRunner, path: str, *, dependencies: Optional[List[str]] = None
) -> None:
    rule_runner.add_to_build_file(
        path, f"python_library(name='target', sources=[], dependencies={dependencies or []})"
    )


def create_python_requirement_library(rule_runner: RuleRunner, name: str) -> None:
    rule_runner.add_to_build_file(
        "3rdparty/python",
        dedent(
            f"""\
            python_requirement_library(
                name='{name}',
                requirements=['{name}==1.0.0'],
            )
            """
        ),
    )


def assert_dependencies(
    rule_runner: RuleRunner,
    *,
    specs: List[str],
    output_format: OutputFormat = OutputFormat.text,
    expected: List[str],
    transitive: bool = False,
    dependency_type: DependencyType = DependencyType.SOURCE,
) -> None:
    args = [f"--type={dependency_type.value}"]
    if transitive:
        args.append("--transitive")
    result = rule_runner.run_goal_rule(Dependencies, args=[*args, *specs])
    assert result.stdout.splitlines() == expected


def test_no_target(rule_runner: RuleRunner) -> None:
    assert_dependencies(rule_runner, specs=[], expected=[])
    assert_dependencies(rule_runner, specs=[], expected=[], transitive=True)
    assert_dependencies(rule_runner, specs=[], output_format=OutputFormat.json, expected=["{}"])
    assert_dependencies(
        rule_runner, specs=[], output_format=OutputFormat.json, expected=["{}"], transitive=True
    )


def test_no_dependencies(rule_runner: RuleRunner) -> None:
    create_python_library(rule_runner, path="some/target")
    assert_dependencies(rule_runner, specs=["some/target"], expected=[])
    assert_dependencies(rule_runner, specs=["some/target"], expected=[], transitive=True)
    assert_dependencies(
        rule_runner, specs=["some/target"], output_format=OutputFormat.json, expected=["{}"]
    )
    assert_dependencies(
        rule_runner,
        specs=["some/target"],
        output_format=OutputFormat.json,
        expected=["{}"],
        transitive=True,
    )


def test_special_cased_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.add_to_build_file(
        "",
        dedent(
            """\
            special_deps_tgt(name='t1')
            special_deps_tgt(name='t2', special_deps=[':t1'])
            special_deps_tgt(name='t3', special_deps=[':t2'])
            """
        ),
    )
    assert_dependencies(rule_runner, specs=["//:t3"], expected=["//:t2"])
    assert_dependencies(rule_runner, specs=["//:t3"], expected=["//:t1", "//:t2"], transitive=True)
    assert_dependencies(
        rule_runner,
        specs=["//:t3"],
        output_format=OutputFormat.json,
        expected=dedent(
            """\
            {
                "base": [
                    "//:t2"
                ]
            }"""
        ).splitlines(),
    )
    assert_dependencies(
        rule_runner,
        specs=["//:t3"],
        output_format=OutputFormat.json,
        expected=dedent(
            """\
            {
               "base": [
                   "//:t1",
                   "//:t2"
                ]
            }"""
        ).splitlines(),
        transitive=True,
    )


def test_python_dependencies(rule_runner: RuleRunner) -> None:
    create_python_requirement_library(rule_runner, name="req1")
    create_python_requirement_library(rule_runner, name="req2")
    create_python_library(rule_runner, path="dep/target")
    create_python_library(
        rule_runner, path="some/target", dependencies=["dep/target", "3rdparty/python:req1"]
    )
    create_python_library(
        rule_runner, path="some/other/target", dependencies=["some/target", "3rdparty/python:req2"]
    )

    assert_deps = partial(assert_dependencies, rule_runner)

    # `--type=source`
    assert_deps(
        specs=["some/other/target"],
        dependency_type=DependencyType.SOURCE,
        expected=["3rdparty/python:req2", "some/target"],
    )
    assert_deps(
        specs=["some/other/target"],
        transitive=True,
        dependency_type=DependencyType.SOURCE,
        expected=["3rdparty/python:req1", "3rdparty/python:req2", "dep/target", "some/target"],
    )

    # `--type=3rdparty`
    assert_deps(
        specs=["some/other/target"],
        dependency_type=DependencyType.THIRD_PARTY,
        expected=["req2==1.0.0"],
    )
    assert_deps(
        specs=["some/other/target"],
        transitive=True,
        dependency_type=DependencyType.THIRD_PARTY,
        expected=["req1==1.0.0", "req2==1.0.0"],
    )

    # `--type=source-and-3rdparty`
    assert_deps(
        specs=["some/other/target"],
        transitive=False,
        dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
        expected=["3rdparty/python:req2", "some/target", "req2==1.0.0"],
    )
    assert_deps(
        specs=["some/other/target"],
        transitive=True,
        dependency_type=DependencyType.SOURCE_AND_THIRD_PARTY,
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target",
            "some/target",
            "req1==1.0.0",
            "req2==1.0.0",
        ],
    )

    # Glob the whole repo. `some/other/target` should not be included because nothing depends
    # on it.
    assert_deps(
        specs=["::"],
        expected=["3rdparty/python:req1", "3rdparty/python:req2", "dep/target", "some/target"],
    )
    assert_deps(
        specs=["::"],
        transitive=True,
        expected=["3rdparty/python:req1", "3rdparty/python:req2", "dep/target", "some/target"],
    )
