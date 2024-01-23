# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import json
from functools import partial
from textwrap import dedent
from typing import List, Optional

import pytest

from pants.backend.project_info.dependencies import Dependencies, DependenciesOutputFormat, rules
from pants.backend.python import target_types_rules
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourcesGeneratorTarget
from pants.engine.target import SpecialCasedDependencies, Target
from pants.testutil.python_rule_runner import PythonRuleRunner


# We verify that any subclasses of `SpecialCasedDependencies` will show up with the `dependencies`
# goal by creating a mock target.
class SpecialDepsField(SpecialCasedDependencies):
    alias = "special_deps"


class SpecialDepsTarget(Target):
    alias = "special_deps_tgt"
    core_fields = (SpecialDepsField,)


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    return PythonRuleRunner(
        rules=[
            *rules(),
            *target_types_rules.rules(),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonRequirementTarget, SpecialDepsTarget],
    )


def create_python_sources(
    rule_runner: PythonRuleRunner, directory: str, *, dependencies: Optional[List[str]] = None
) -> None:
    rule_runner.write_files(
        {
            f"{directory}/BUILD": f"python_sources(name='target', dependencies={dependencies or []})",
            f"{directory}/a.py": "",
        }
    )


def create_python_requirement_tgts(rule_runner: PythonRuleRunner, *names: str) -> None:
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


def create_targets(rule_runner: PythonRuleRunner) -> None:
    """Create necessary targets used in tests before querying the graph for dependencies."""
    create_python_requirement_tgts(rule_runner, "req1", "req2")
    create_python_sources(rule_runner, "dep/target")
    create_python_sources(
        rule_runner, "some/target", dependencies=["dep/target", "3rdparty/python:req1"]
    )
    create_python_sources(
        rule_runner,
        "some/other/target",
        dependencies=["some/target", "3rdparty/python:req2"],
    )


def assert_dependencies(
    rule_runner: PythonRuleRunner,
    *,
    specs: List[str],
    expected: List[str],
    transitive: bool = False,
    closed: bool = False,
    output_format: DependenciesOutputFormat = DependenciesOutputFormat.text,
) -> None:
    args = []
    if transitive:
        args.append("--transitive")
    if closed:
        args.append("--closed")
    args.append(f"--format={output_format.value}")

    result = rule_runner.run_goal_rule(
        Dependencies, args=[*args, *specs], env_inherit={"PATH", "PYENV_ROOT", "HOME"}
    )
    if output_format == DependenciesOutputFormat.text:
        assert result.stdout.splitlines() == expected
    elif output_format == DependenciesOutputFormat.json:
        assert json.loads(result.stdout) == expected


def test_no_target(rule_runner: PythonRuleRunner) -> None:
    assert_dependencies(rule_runner, specs=[], expected=[])
    assert_dependencies(rule_runner, specs=[], expected=[], transitive=True)


def test_no_dependencies(rule_runner: PythonRuleRunner) -> None:
    create_python_sources(rule_runner, "some/target")
    assert_dependencies(rule_runner, specs=["some/target/a.py"], expected=[])
    assert_dependencies(rule_runner, specs=["some/target/a.py"], expected=[], transitive=True)
    assert_dependencies(
        rule_runner, specs=["some/target/a.py"], expected=["some/target/a.py"], closed=True
    )
    assert_dependencies(
        rule_runner,
        specs=["some/target/a.py"],
        expected=["some/target/a.py"],
        transitive=True,
        closed=True,
    )


def test_special_cased_dependencies(rule_runner: PythonRuleRunner) -> None:
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


def test_python_dependencies(rule_runner: PythonRuleRunner) -> None:
    create_targets(rule_runner)
    assert_deps = partial(
        assert_dependencies,
        rule_runner,
        output_format=DependenciesOutputFormat.text,
    )

    assert_deps(
        specs=["some/other/target:target"],
        transitive=False,
        expected=["some/other/target/a.py"],
    )
    assert_deps(
        specs=["some/other/target/a.py"],
        transitive=False,
        expected=["3rdparty/python:req2", "some/target/a.py"],
    )
    assert_deps(
        specs=["some/other/target:target"],
        transitive=True,
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target/a.py",
            "some/other/target/a.py",
            "some/target/a.py",
        ],
    )

    # Glob the whole repo. `some/other/target` should not be included if --closed is not set,
    # because nothing depends on it.
    assert_deps(
        specs=["::"],
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target/a.py",
            "some/other/target/a.py",
            "some/target/a.py",
        ],
    )
    assert_deps(
        specs=["::"],
        transitive=True,
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target/a.py",
            "some/other/target/a.py",
            "some/target/a.py",
        ],
    )
    assert_deps(
        specs=["::"],
        expected=[
            "3rdparty/python:req1",
            "3rdparty/python:req2",
            "dep/target/a.py",
            "dep/target:target",
            "some/other/target/a.py",
            "some/other/target:target",
            "some/target/a.py",
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
            "dep/target/a.py",
            "dep/target:target",
            "some/other/target/a.py",
            "some/other/target:target",
            "some/target/a.py",
            "some/target:target",
        ],
        closed=True,
    )


def test_python_dependencies_output_format_json_direct_deps(rule_runner: PythonRuleRunner) -> None:
    create_targets(rule_runner)
    assert_deps = partial(
        assert_dependencies,
        rule_runner,
        output_format=DependenciesOutputFormat.json,
    )

    # input: single module
    assert_deps(
        specs=["some/target/a.py"],
        transitive=False,
        expected={
            "some/target/a.py": [
                "3rdparty/python:req1",
                "dep/target/a.py",
            ]
        },
    )

    # input: multiple modules
    assert_deps(
        specs=["some/target/a.py", "some/other/target/a.py"],
        transitive=False,
        expected={
            "some/target/a.py": [
                "3rdparty/python:req1",
                "dep/target/a.py",
            ],
            "some/other/target/a.py": [
                "3rdparty/python:req2",
                "some/target/a.py",
            ],
        },
    )

    # input: directory, recursively
    assert_deps(
        specs=["some::"],
        transitive=False,
        expected={
            "some/target:target": [
                "some/target/a.py",
            ],
            "some/target/a.py": [
                "3rdparty/python:req1",
                "dep/target/a.py",
            ],
            "some/other/target:target": [
                "some/other/target/a.py",
            ],
            "some/other/target/a.py": [
                "3rdparty/python:req2",
                "some/target/a.py",
            ],
        },
    )
    assert_deps(
        specs=["some/other/target:target"],
        transitive=True,
        expected={
            "some/other/target:target": [
                "3rdparty/python:req1",
                "3rdparty/python:req2",
                "dep/target/a.py",
                "some/other/target/a.py",
                "some/target/a.py",
            ]
        },
    )


def test_python_dependencies_output_format_json_transitive_deps(
    rule_runner: PythonRuleRunner,
) -> None:
    create_targets(rule_runner)
    assert_deps = partial(
        assert_dependencies,
        rule_runner,
        output_format=DependenciesOutputFormat.json,
    )

    # input: single module
    assert_deps(
        specs=["some/target/a.py"],
        transitive=True,
        expected={
            "some/target/a.py": [
                "3rdparty/python:req1",
                "dep/target/a.py",
            ]
        },
    )

    # input: multiple modules
    assert_deps(
        specs=["some/target/a.py", "some/other/target/a.py"],
        transitive=True,
        expected={
            "some/target/a.py": [
                "3rdparty/python:req1",
                "dep/target/a.py",
            ],
            "some/other/target/a.py": [
                "3rdparty/python:req1",
                "3rdparty/python:req2",
                "dep/target/a.py",
                "some/target/a.py",
            ],
        },
    )

    # input: directory, recursively
    assert_deps(
        specs=["some::"],
        transitive=True,
        expected={
            "some/target:target": [
                "3rdparty/python:req1",
                "dep/target/a.py",
                "some/target/a.py",
            ],
            "some/target/a.py": [
                "3rdparty/python:req1",
                "dep/target/a.py",
            ],
            "some/other/target:target": [
                "3rdparty/python:req1",
                "3rdparty/python:req2",
                "dep/target/a.py",
                "some/other/target/a.py",
                "some/target/a.py",
            ],
            "some/other/target/a.py": [
                "3rdparty/python:req1",
                "3rdparty/python:req2",
                "dep/target/a.py",
                "some/target/a.py",
            ],
        },
    )
