# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent
from typing import Iterable

import pytest

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
from pants.backend.python.util_rules.entry_points import (
    GenerateEntryPointsTxtFromEntryPointDependenciesRequest,
    InferEntryPointDependencies,
    PythonTestsEntryPointDependenciesInferenceFieldSet,
)
from pants.backend.python.util_rules.entry_points import rules as entry_points_rules
from pants.engine.addresses import Address
from pants.engine.fs import CreateDigest, DigestContents, FileContent
from pants.engine.internals.native_engine import EMPTY_DIGEST, Digest
from pants.engine.target import InferredDependencies
from pants.testutil.rule_runner import QueryRule, RuleRunner

# random set of runner names to use in tests
st2_runners = ["noop", "foobar"]


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
                            "st2common.runners.runner": {{
                                "{runner}": "{runner}_runner.{runner}_runner",
                            }},
                            "console_scripts": {{
                                "some-thing": "{runner}_runner.thing:main",
                            }},
                        }},
                    )
                    """
                )
                + extra_build_contents.format(runner=runner),
                f"runners/{runner}_runner/{runner}_runner/BUILD": "python_sources()",
                f"runners/{runner}_runner/{runner}_runner/__init__.py": "",
                f"runners/{runner}_runner/{runner}_runner/{runner}_runner.py": "",
                f"runners/{runner}_runner/{runner}_runner/thing.py": dedent(
                    """\
                    def main():
                        return True
                    """
                ),
            }
        )


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *entry_points_rules(),
            *python_target_types_rules(),
            QueryRule(InferredDependencies, (InferEntryPointDependencies,)),
            QueryRule(
                PytestPluginSetup,
                (GenerateEntryPointsTxtFromEntryPointDependenciesRequest,),
            ),
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
        },
    )
    write_test_files(rule_runner)
    args = [
        "--source-root-patterns=runners/*_runner",
    ]
    rule_runner.set_options(args, env_inherit={"PATH", "PYENV_ROOT", "HOME"})
    return rule_runner


# -----------------------------------------------------------------------------------------------
# Tests for dependency inference of python targets (python_tests)
# -----------------------------------------------------------------------------------------------


_noop_runner_addresses = (
    Address(
        "runners/noop_runner/noop_runner",
        relative_file_path="noop_runner.py",
    ),
    Address(
        "runners/noop_runner/noop_runner",
        relative_file_path="thing.py",
    ),
)


@pytest.mark.parametrize(
    "requested_entry_points, expected_dep_addresses",
    (
        # return no entry points
        ([], []),
        (["undefined.group"], []),
        (["console_scripts/undefined-script"], []),
        # return one entry point
        (["st2common.runners.runner"], [_noop_runner_addresses[0]]),
        (["st2common.runners.runner/noop"], [_noop_runner_addresses[0]]),
        (["console_scripts"], [_noop_runner_addresses[1]]),
        (["console_scripts/some-thing"], [_noop_runner_addresses[1]]),
        # return multiple entry points
        (["st2common.runners.runner", "console_scripts"], _noop_runner_addresses),
        (["st2common.runners.runner", "console_scripts/some-thing"], _noop_runner_addresses),
        (["st2common.runners.runner/noop", "console_scripts/some-thing"], _noop_runner_addresses),
        (["st2common.runners.runner/noop", "console_scripts"], _noop_runner_addresses),
        # return all entry points
        (["st2common.runners.runner", "*"], _noop_runner_addresses),
        (["*", "gui_scripts"], _noop_runner_addresses),
        (["*"], _noop_runner_addresses),
    ),
)
def test_infer_entry_point_dependencies(  # also tests get_filtered_entry_point_dependencies
    rule_runner: RuleRunner,
    requested_entry_points: list[str],
    expected_dep_addresses: Iterable[Address],
) -> None:
    rule_runner.write_files(
        {
            "src/foobar/BUILD": dedent(
                f"""\
                python_tests(
                    name="tests",
                    entry_point_dependencies={{
                        "//runners/noop_runner": {repr(requested_entry_points)},
                    }},
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
                InferEntryPointDependencies(
                    PythonTestsEntryPointDependenciesInferenceFieldSet.create(target)
                )
            ],
        )

    # This also asserts that these should NOT be inferred dependencies:
    #   - anything from distributions other than noop_runner
    #   - the python_distribution itself at Address(f"runners/noop_runner")
    assert run_dep_inference(
        Address("src/foobar", target_name="tests", relative_file_path="test_something.py"),
    ) == InferredDependencies(expected_dep_addresses)


# -----------------------------------------------------------------------------------------------
# Tests for entry_points.txt generation
# -----------------------------------------------------------------------------------------------


# based on get_snapshot from pantsbuild/pants.git/src/python/pants/backend/python/lint/black/rules_integration_test.py
def get_digest(rule_runner: RuleRunner, source_files: dict[str, str]) -> Digest:
    files = [FileContent(path, content.encode()) for path, content in source_files.items()]
    return rule_runner.request(Digest, [CreateDigest(files)])


def get_digest_contents(rule_runner: RuleRunner, digest: Digest) -> DigestContents:
    return rule_runner.request(DigestContents, [digest])


_foobar_entry_points_txt_files = (
    dedent(
        """\
        [console_scripts]
        some-thing = foobar_runner.thing:main

        """
    ),
    dedent(
        """\
        [st2common.runners.runner]
        foobar = foobar_runner.foobar_runner

        """
    ),
    dedent(
        """\
        [console_scripts]
        some-thing = foobar_runner.thing:main

        [st2common.runners.runner]
        foobar = foobar_runner.foobar_runner

        """
    ),
)


@pytest.mark.parametrize(
    "requested_entry_points, expected_entry_points_txt",
    (
        # return no entry points
        ([], None),
        (["undefined.group"], None),
        (["console_scripts/undefined-script"], None),
        # return one entry point
        (["st2common.runners.runner"], _foobar_entry_points_txt_files[1]),
        (["st2common.runners.runner/foobar"], _foobar_entry_points_txt_files[1]),
        (["console_scripts"], _foobar_entry_points_txt_files[0]),
        (["console_scripts/some-thing"], _foobar_entry_points_txt_files[0]),
        # return multiple entry points
        (["st2common.runners.runner", "console_scripts"], _foobar_entry_points_txt_files[2]),
        (
            ["st2common.runners.runner", "console_scripts/some-thing"],
            _foobar_entry_points_txt_files[2],
        ),
        (
            ["st2common.runners.runner/foobar", "console_scripts/some-thing"],
            _foobar_entry_points_txt_files[2],
        ),
        (
            ["st2common.runners.runner/foobar", "console_scripts"],
            _foobar_entry_points_txt_files[2],
        ),
        # return all entry points
        (["st2common.runners.runner", "*"], _foobar_entry_points_txt_files[2]),
        (["*", "gui_scripts"], _foobar_entry_points_txt_files[2]),
        (["*"], _foobar_entry_points_txt_files[2]),
    ),
)
def test_generate_entry_points_txt_from_entry_point_dependencies(
    rule_runner: RuleRunner,
    requested_entry_points: list[str],
    expected_entry_points_txt: str | None,
) -> None:
    rule_runner.write_files(
        {
            "src/foobar/BUILD": dedent(
                f"""\
                python_tests(
                    name="tests",
                    entry_point_dependencies={{
                        "//runners/foobar_runner": {repr(requested_entry_points)},
                    }},
                )
                """
            ),
            "src/foobar/test_something.py": "",
        }
    )

    entry_points_txt_path = "runners/foobar_runner/foobar_runner.egg-info/entry_points.txt"
    if expected_entry_points_txt is None:
        expected_digest = EMPTY_DIGEST
    else:
        expected_digest = get_digest(
            rule_runner,
            {entry_points_txt_path: expected_entry_points_txt},
        )

    target = rule_runner.get_target(
        Address("src/foobar", target_name="tests", relative_file_path="test_something.py"),
    )
    response = rule_runner.request(
        PytestPluginSetup,
        [GenerateEntryPointsTxtFromEntryPointDependenciesRequest(target)],
    )
    contents = get_digest_contents(rule_runner, response.digest)
    if expected_entry_points_txt is None:
        assert not contents
    else:
        assert len(contents) == 1
        assert contents[0].path == entry_points_txt_path
        assert contents[0].content == expected_entry_points_txt.encode()

    assert response == PytestPluginSetup(expected_digest)
