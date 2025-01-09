# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.framework.stevedore.python_target_dependencies import (
    rules as stevedore_dep_rules,
)
from pants.backend.python.framework.stevedore.rules import (
    GenerateEntryPointsTxtFromStevedoreExtensionRequest,
)
from pants.backend.python.framework.stevedore.rules import rules as stevedore_rules
from pants.backend.python.framework.stevedore.target_types import StevedoreNamespace
from pants.backend.python.goals.pytest_runner import PytestPluginSetup
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
    PythonTestsGeneratorTarget,
    PythonTestTarget,
)
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.backend.python.util_rules.entry_points import rules as entry_points_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_DIGEST, CreateDigest, Digest, FileContent
from pants.testutil.rule_runner import QueryRule, RuleRunner

# random set of runner names to use in tests
st2_runners = ["noop", "python", "foobar"]


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *entry_points_rules(),
            *python_target_types_rules(),
            *stevedore_dep_rules(),
            *stevedore_rules(),
            QueryRule(
                PytestPluginSetup,
                (GenerateEntryPointsTxtFromStevedoreExtensionRequest,),
            ),
        ],
        target_types=[
            PythonSourceTarget,
            PythonSourcesGeneratorTarget,
            PythonTestTarget,
            PythonTestsGeneratorTarget,
            PythonDistribution,
        ],
        objects={
            "python_artifact": PythonArtifact,
            "stevedore_namespace": StevedoreNamespace,
        },
    )


# based on get_snapshot from pantsbuild/pants.git/src/python/pants/backend/python/lint/black/rules_integration_test.py
def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def test_generate_entry_points_txt_from_stevedore_extension(
    rule_runner: RuleRunner,
) -> None:
    rule_runner.write_files(
        {
            "src/one_ns/BUILD": dedent(
                """\
                python_tests(
                    name="tests",
                    stevedore_namespaces=["st2common.runners.runner"],
                )
                """
            ),
            "src/one_ns/test_something.py": "",
            "src/two_ns/BUILD": dedent(
                """\
                python_tests(
                    name="tests",
                    stevedore_namespaces=[
                        "st2common.runners.runner",
                        "some.thing.else",
                    ],
                )
                """
            ),
            "src/two_ns/test_something.py": "",
            "src/no_deps/BUILD": dedent(
                """\
                python_tests(
                    name="tests",
                    stevedore_namespaces=["namespace.without.implementations"],
                )
                """
            ),
            "src/no_deps/test_something.py": "",
        }
    )
    for runner in st2_runners:
        rule_runner.write_files(
            {
                f"runners/{runner}_runner/BUILD": dedent(
                    # to test consistent sorting, reverse sort by namespace
                    # and then reverse sort entry_points by key.
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
                                "{runner}2": "{runner}_runner.thing2",
                                "{runner}1": "{runner}_runner.thing1",
                            }},
                        }},
                    )
                    """
                ),
                f"runners/{runner}_runner/{runner}_runner/BUILD": "python_sources()",
                f"runners/{runner}_runner/{runner}_runner/__init__.py": "",
                f"runners/{runner}_runner/{runner}_runner/{runner}_runner.py": "",
                f"runners/{runner}_runner/{runner}_runner/thing1.py": "",
                f"runners/{runner}_runner/{runner}_runner/thing2.py": "",
            }
        )

    args = [
        "--source-root-patterns=runners/*_runner",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})

    def gen_entry_points_txt(address: Address) -> PytestPluginSetup:
        target = rule_runner.get_target(address)
        return rule_runner.request(
            PytestPluginSetup,
            [GenerateEntryPointsTxtFromStevedoreExtensionRequest(target)],
        )

    # test with no implementations of the requested namespace
    assert gen_entry_points_txt(
        Address("src/no_deps", target_name="tests", relative_file_path="test_something.py"),
    ) == PytestPluginSetup(EMPTY_DIGEST)

    assert gen_entry_points_txt(
        Address("src/one_ns", target_name="tests", relative_file_path="test_something.py"),
    ) == PytestPluginSetup(
        get_digest(
            rule_runner,
            {
                f"runners/{runner}_runner/{runner}_runner.egg-info/entry_points.txt": dedent(
                    f"""\
                    [st2common.runners.runner]
                    {runner} = {runner}_runner.{runner}_runner

                    """
                )
                for runner in st2_runners
            },
        )
    )

    assert gen_entry_points_txt(
        Address("src/two_ns", target_name="tests", relative_file_path="test_something.py"),
    ) == PytestPluginSetup(
        get_digest(
            rule_runner,
            {
                f"runners/{runner}_runner/{runner}_runner.egg-info/entry_points.txt": dedent(
                    # Note that these are sorted for better cacheability
                    f"""\
                    [some.thing.else]
                    {runner}1 = {runner}_runner.thing1
                    {runner}2 = {runner}_runner.thing2

                    [st2common.runners.runner]
                    {runner} = {runner}_runner.{runner}_runner

                    """
                )
                for runner in st2_runners
            },
        )
    )
