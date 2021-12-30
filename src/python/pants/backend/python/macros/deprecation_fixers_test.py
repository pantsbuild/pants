# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python.macros import deprecation_fixers
from pants.backend.python.macros.deprecation_fixers import GeneratorRename, MacroRenames
from pants.backend.python.macros.pipenv_requirements_caof import PipenvRequirementsCAOF
from pants.backend.python.macros.poetry_requirements_caof import PoetryRequirementsCAOF
from pants.backend.python.macros.python_requirements_caof import PythonRequirementsCAOF
from pants.backend.python.target_types import PythonRequirementsFile, PythonRequirementTarget
from pants.core.target_types import GenericTarget
from pants.engine.addresses import Address
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(*deprecation_fixers.rules(), QueryRule(MacroRenames, [])),
        target_types=[GenericTarget, PythonRequirementsFile, PythonRequirementTarget],
        context_aware_object_factories={
            "python_requirements": PythonRequirementsCAOF,
            "poetry_requirements": PoetryRequirementsCAOF,
            "pipenv_requirements": PipenvRequirementsCAOF,
        },
    )


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
    renames = rule_runner.request(MacroRenames, [])
    assert renames.generators == (
        GeneratorRename("BUILD", "python_requirements", "reqs"),
        GeneratorRename("pipenv/BUILD", "pipenv_requirements", None),
        GeneratorRename("poetry/BUILD", "poetry_requirements", None),
        GeneratorRename("reqs/BUILD", "python_requirements", "reqs"),
    )
    assert renames.generated == FrozenDict(
        {
            Address("", target_name="req"): Address("", target_name="reqs", generated_name="req"),
            Address("pipenv", target_name="req1"): Address(
                "pipenv", target_name="pipenv", generated_name="req1"
            ),
            Address("pipenv", target_name="req2"): Address(
                "pipenv", target_name="pipenv", generated_name="req2"
            ),
            Address("poetry", target_name="req1"): Address(
                "poetry", target_name="poetry", generated_name="req1"
            ),
            Address("poetry", target_name="req2"): Address(
                "poetry", target_name="poetry", generated_name="req2"
            ),
            Address("reqs", target_name="req1"): Address(
                "reqs", target_name="reqs", generated_name="req1"
            ),
            Address("reqs", target_name="req2"): Address(
                "reqs", target_name="reqs", generated_name="req2"
            ),
        }
    )
    assert '* `python_requirements` in BUILD: add `name="reqs"' in caplog.text
    assert '* `python_requirements` in reqs/BUILD: add `name="reqs"' in caplog.text
    assert "* `poetry_requirements`" not in caplog.text
    assert "* `pipenv_requirements`" not in caplog.text
