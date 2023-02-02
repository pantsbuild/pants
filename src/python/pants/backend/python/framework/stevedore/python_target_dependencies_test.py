# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.framework.stevedore.python_target_dependencies import (
    InferStevedoreNamespacesDependencies,
    PythonTestsStevedoreNamespaceInferenceFieldSet,
    StevedoreExtensions,
)
from pants.backend.python.framework.stevedore.python_target_dependencies import (
    rules as stevedore_dep_rules,
)
from pants.backend.python.framework.stevedore.target_types import (
    AllStevedoreExtensionTargets,
    StevedoreExtensionTargets,
    StevedoreNamespace,
    StevedoreNamespacesField,
    StevedoreNamespacesProviderTargetsRequest,
)
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.engine.addresses import Address
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict

# random set of runner names to use in tests
st2_runners = ["noop", "python", "foobar"]


def write_test_files(rule_runner: RuleRunner, extra_build_contents: str = ""):
    for runner in st2_runners:
        rule_runner.write_files(
            {
                f"runners/{runner}_runner/BUILD": dedent(
                    f"""\
                    python_distribution(
                        provides=python_artifact(
                            name="stackstorm-runner-{runner}",
                        ),
                        entry_points={{
                            stevedore_namespace("st2common.runners.runner"): {{
                                "{runner}": "{runner}_runner.{runner}_runner",
                            }},
                            stevedore_namespace("some.thing.else"): {{
                                "{runner}": "{runner}_runner.thing",
                            }},
                        }},
                    )
                    """
                )
                + extra_build_contents.format(runner=runner),
                f"runners/{runner}_runner/{runner}_runner/BUILD": "python_sources()",
                f"runners/{runner}_runner/{runner}_runner/__init__.py": "",
                f"runners/{runner}_runner/{runner}_runner/{runner}_runner.py": "",
                f"runners/{runner}_runner/{runner}_runner/thing.py": "",
            }
        )


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *python_target_types_rules(),
            *stevedore_dep_rules(),
            QueryRule(AllStevedoreExtensionTargets, ()),
            QueryRule(StevedoreExtensions, ()),
            QueryRule(StevedoreExtensionTargets, (StevedoreNamespacesProviderTargetsRequest,)),
            QueryRule(InferredDependencies, (InferStevedoreNamespacesDependencies,)),
        ],
        target_types=[
            PythonDistribution,
            PythonSourceTarget,
            PythonSourcesGeneratorTarget,
            PythonTestTarget,
            PythonTestsGeneratorTarget,
        ],
        objects={
            "python_artifact": PythonArtifact,
            "stevedore_namespace": StevedoreNamespace,
        },
    )
    write_test_files(rule_runner)
    args = [
        "--source-root-patterns=runners/*_runner",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


# -----------------------------------------------------------------------------------------------
# Tests for utility rules
# -----------------------------------------------------------------------------------------------


def test_find_all_stevedore_extension_targets(rule_runner: RuleRunner) -> None:
    assert rule_runner.request(AllStevedoreExtensionTargets, []) == AllStevedoreExtensionTargets(
        rule_runner.get_target(Address(f"runners/{runner}_runner"))
        for runner in sorted(st2_runners)
    )


def test_map_stevedore_extensions(rule_runner: RuleRunner) -> None:
    assert rule_runner.request(StevedoreExtensions, []) == StevedoreExtensions(
        FrozenDict(
            {
                StevedoreNamespace("some.thing.else"): tuple(
                    rule_runner.get_target(Address(f"runners/{runner}_runner"))
                    for runner in sorted(st2_runners)
                ),
                StevedoreNamespace("st2common.runners.runner"): tuple(
                    rule_runner.get_target(Address(f"runners/{runner}_runner"))
                    for runner in sorted(st2_runners)
                ),
            }
        )
    )


def test_find_python_distributions_with_entry_points_in_stevedore_namespaces(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/foobar/BUILD": dedent(
                """\
                python_tests(
                    name="tests",
                    stevedore_namespaces=["some.thing.else"],
                )
                """
            ),
            "src/foobar/test_something.py": "",
        }
    )

    # use set as the order of targets is not consistent and is not easily sorted
    assert set(
        rule_runner.request(
            StevedoreExtensionTargets,
            [
                StevedoreNamespacesProviderTargetsRequest(
                    rule_runner.get_target(Address("src/foobar", target_name="tests")).get(
                        StevedoreNamespacesField
                    )
                ),
            ],
        )
    ) == set(
        StevedoreExtensionTargets(
            (
                rule_runner.get_target(Address(f"runners/{runner}_runner"))
                for runner in sorted(st2_runners)
            )
        )
    )


# -----------------------------------------------------------------------------------------------
# Tests for dependency inference of python targets (python_tests)
# -----------------------------------------------------------------------------------------------


def test_infer_stevedore_namespace_dependencies(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/foobar/BUILD": dedent(
                """\
                python_tests(
                    name="tests",
                    stevedore_namespaces=["st2common.runners.runner"],
                )
                """
            ),
            "src/foobar/test_something.py": "",
        }
    )

    def run_dep_inference(address: Address) -> InferredDependencies:
        target = rule_runner.get_target(address)
        return rule_runner.request(
            InferredDependencies,
            [
                InferStevedoreNamespacesDependencies(
                    PythonTestsStevedoreNamespaceInferenceFieldSet.create(target)
                )
            ],
        )

    # This asserts that these should NOT be inferred dependencies:
    #   - stevedore_namespace(some.thing.else) -> {runner}_runner.thing
    #   - the python_distribution itself at Address(f"runners/{runner}_runner")
    # It should only infer the stevedore_namespace(st2common.runners.runner) deps.
    assert run_dep_inference(
        Address("src/foobar", target_name="tests", relative_file_path="test_something.py"),
    ) == InferredDependencies(
        [
            Address(
                f"runners/{runner}_runner/{runner}_runner",
                relative_file_path=f"{runner}_runner.py",
            )
            for runner in st2_runners
        ],
    )
