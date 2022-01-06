# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.python.macros import deprecation_fixers
from pants.backend.python.macros.deprecation_fixers import (
    GeneratorRename,
    MacroRenames,
    MacroRenamesRequest,
    UpdatePythonMacrosRequest,
)
from pants.backend.python.macros.pipenv_requirements_caof import PipenvRequirementsCAOF
from pants.backend.python.macros.poetry_requirements_caof import PoetryRequirementsCAOF
from pants.backend.python.macros.python_requirements_caof import PythonRequirementsCAOF
from pants.backend.python.target_types import PythonRequirementsFileTarget, PythonRequirementTarget
from pants.core.goals.update_build_files import RewrittenBuildFile
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=(
            *deprecation_fixers.rules(),
            QueryRule(MacroRenames, [MacroRenamesRequest]),
            QueryRule(RewrittenBuildFile, [UpdatePythonMacrosRequest]),
        ),
        target_types=[GenericTarget, PythonRequirementsFileTarget, PythonRequirementTarget],
        context_aware_object_factories={
            "python_requirements": PythonRequirementsCAOF,
            "poetry_requirements": PoetryRequirementsCAOF,
            "pipenv_requirements": PipenvRequirementsCAOF,
        },
        use_deprecated_python_macros=True,
    )
    rule_runner.set_options(["--update-build-files-fix-python-macros"])
    return rule_runner


def test_determine_macro_changes(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.write_files(
        {
            "requirements.txt": "req",
            "BUILD": "python_requirements()",
            "reqs/requirements.txt": "req1\nreq2",
            "reqs/BUILD": dedent(
                """\
                # This target takes the default `name`.
                target()
                python_requirements()
                """
            ),
            "poetry/pyproject.toml": dedent(
                """\
                [tool.poetry.dependencies]
                req1 = "*"
                req2 = "*"
                """
            ),
            "poetry/BUILD": "poetry_requirements()",
            "pipenv/Pipfile.lock": dedent(
                """\
                {"default": {"req1": {"version": "==1"}, "req2": {"version": "==1"}}, "develop": {}}
                """
            ),
            "pipenv/BUILD": "pipenv_requirements()",
        }
    )
    renames = rule_runner.request(MacroRenames, [MacroRenamesRequest()])
    assert renames.generators == (
        GeneratorRename("BUILD", "python_requirements", "reqs"),
        GeneratorRename("pipenv/BUILD", "pipenv_requirements", None),
        GeneratorRename("poetry/BUILD", "poetry_requirements", None),
        GeneratorRename("reqs/BUILD", "python_requirements", "reqs"),
    )
    assert renames.generated == FrozenDict(
        {
            Address("", target_name="req"): (
                Address("", target_name="reqs", generated_name="req"),
                "python_requirements",
            ),
            Address("pipenv", target_name="req1"): (
                Address("pipenv", target_name="pipenv", generated_name="req1"),
                "pipenv_requirements",
            ),
            Address("pipenv", target_name="req2"): (
                Address("pipenv", target_name="pipenv", generated_name="req2"),
                "pipenv_requirements",
            ),
            Address("poetry", target_name="req1"): (
                Address("poetry", target_name="poetry", generated_name="req1"),
                "poetry_requirements",
            ),
            Address("poetry", target_name="req2"): (
                Address("poetry", target_name="poetry", generated_name="req2"),
                "poetry_requirements",
            ),
            Address("reqs", target_name="req1"): (
                Address("reqs", target_name="reqs", generated_name="req1"),
                "python_requirements",
            ),
            Address("reqs", target_name="req2"): (
                Address("reqs", target_name="reqs", generated_name="req2"),
                "python_requirements",
            ),
        }
    )
    assert '* `python_requirements` in BUILD: add `name="reqs"' in caplog.text
    assert '* `python_requirements` in reqs/BUILD: add `name="reqs"' in caplog.text
    assert "* `poetry_requirements`" not in caplog.text
    assert "* `pipenv_requirements`" not in caplog.text


def test_update_macro_references(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "requirements.txt": "req",
            "BUILD": "python_requirements()",
            "default_name/requirements.txt": "req",
            "default_name/BUILD": dedent(
                """\
                python_requirements(
                    # Note the relative address.
                    overrides={'req': {'dependencies': [':req']}},
                )
                """
            ),
            "name_claimed/requirements.txt": "req",
            "name_claimed/BUILD": dedent(
                """\
                # This target takes the default `name`.
                target()

                python_requirements(
                    # Note the relative address.
                    overrides={'req': {'dependencies': [':req']}},
                )
                """
            ),
            "poetry/pyproject.toml": dedent(
                """\
                [tool.poetry.dependencies]
                req = "*"
                """
            ),
            "poetry/BUILD": "poetry_requirements()",
            "pipenv/Pipfile.lock": '{"default": {"req": {"version": "==1"}}, "develop": {}}',
            "pipenv/BUILD": "pipenv_requirements()",
            "deps/BUILD": dedent(
                """\
                target(
                    dependencies=[
                        "//:req",  # a comment
                        "default_name:req",
                        'name_claimed:req',
                        "poetry:req",
                        "pipenv:req",
                        "unrelated",
                        "unrelated#generated",
                        "unrelated:tgt",
                        "unrelated:tgt#generated",
                        "f.txt",
                        "f.txt:tgt",
                        # Regression test for a file target breaking pantsbuild/pants.
                        "BUILD_ROOT:tgt",
                        # Two fixes on the same line.
                        "default_name:req", "default_name:req",
                        "name_claimed:req", "name_claimed:req",
                    ],
                )
                """
            ),
        }
    )

    def run_fixer(build_file: str) -> RewrittenBuildFile:
        request = UpdatePythonMacrosRequest(
            build_file,
            tuple(Path(rule_runner.build_root, build_file).read_text().splitlines()),
            colors_enabled=False,
        )
        return rule_runner.request(RewrittenBuildFile, [request])

    # These BUILD files should not change.
    assert not run_fixer("BUILD").change_descriptions
    assert not run_fixer("poetry/BUILD").change_descriptions
    assert not run_fixer("pipenv/BUILD").change_descriptions

    result = run_fixer("default_name/BUILD")
    assert (
        list(result.lines)
        == dedent(
            """\
            python_requirements(
                # Note the relative address.
                overrides={'req': {'dependencies': ['#req']}},
            )
            """
        ).splitlines()
    )
    assert len(result.change_descriptions) == 1
    assert "python_requirements" in result.change_descriptions[0]

    result = run_fixer("name_claimed/BUILD")
    assert (
        list(result.lines)
        == dedent(
            """\
            # This target takes the default `name`.
            target()

            python_requirements(
                # Note the relative address.
                overrides={'req': {'dependencies': [':reqs#req']}},
            )
            """
        ).splitlines()
    )
    assert len(result.change_descriptions) == 1
    assert "python_requirements" in result.change_descriptions[0]

    result = run_fixer("deps/BUILD")
    assert (
        list(result.lines)
        == dedent(
            """\
            target(
                dependencies=[
                    "//:reqs#req",  # a comment
                    "default_name#req",
                    'name_claimed:reqs#req',
                    "poetry#req",
                    "pipenv#req",
                    "unrelated",
                    "unrelated#generated",
                    "unrelated:tgt",
                    "unrelated:tgt#generated",
                    "f.txt",
                    "f.txt:tgt",
                    # Regression test for a file target breaking pantsbuild/pants.
                    "BUILD_ROOT:tgt",
                    # Two fixes on the same line.
                    "default_name#req", "default_name#req",
                    "name_claimed:reqs#req", "name_claimed:reqs#req",
                ],
            )
            """
        ).splitlines()
    )
    assert len(result.change_descriptions) == 3
