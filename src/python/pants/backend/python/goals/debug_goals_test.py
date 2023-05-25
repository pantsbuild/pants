# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.dependency_inference.rules import (
    ImportOwnerStatus,
    PythonImportDependenciesInferenceFieldSet,
    import_rules,
)
from pants.backend.python.goals import debug_goals
from pants.backend.python.goals.debug_goals import PythonSourceAnalysis
from pants.backend.python.macros import python_requirements
from pants.backend.python.macros.python_requirements import PythonRequirementsTargetGenerator
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.build_graph.address import Address
from pants.core.target_types import FileTarget
from pants.core.target_types import rules as core_target_types_rules
from pants.engine.internals.parametrize import Parametrize
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.testutil.rule_runner import QueryRule


@pytest.fixture
def imports_rule_runner() -> PythonRuleRunner:
    resolves = {"python-default": "", "other": ""}

    rule_runner = PythonRuleRunner(
        rules=[
            *import_rules(),
            *target_types_rules.rules(),
            *core_target_types_rules(),
            *python_requirements.rules(),
            *debug_goals.rules(),
            QueryRule(PythonSourceAnalysis, [PythonImportDependenciesInferenceFieldSet]),
        ],
        target_types=[
            PythonSourceTarget,
            PythonSourcesGeneratorTarget,
            PythonRequirementTarget,
            PythonRequirementsTargetGenerator,
            FileTarget,
        ],
        objects={"parametrize": Parametrize},
    )
    rule_runner.set_options(
        [
            "--python-infer-assets",
            "--python-enable-resolves",
            f"--python-resolves={resolves}",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def test_debug_goals(imports_rule_runner: PythonRuleRunner):
    filedir = "project"
    filename = "t.py"

    imports_rule_runner.write_files(
        {
            str(Path(filedir, filename)): dedent(
                f"""\
                import json  # unownable, root level
                import os.path  # unownable, not root level

                import stuff  # dependency missing
                import watchdog  # dependency included in other resolve
                import yaml  # dependency included

                try:
                    import weakimport  # weakimport missing
                except ImportError:
                    ...

                open("missing.json")
                # missing asset
                open("{filedir}/config.json")
                # asset
                """
            ),
            str(Path(filedir, "BUILD")): dedent(
                f"""\
                python_source(
                    name="t",
                    source="t.py",
                    dependencies=["//{filedir}:config"],
                    resolve="python-default",
                )

                file(
                    name="config",
                    source="config.json",
                )

                python_requirement(
                    name="imported",
                    requirements=["pyyaml"],
                )

                python_requirement(
                    name="other",
                    requirements=["watchdog"],
                    resolve="other",
                )
                """
            ),
            str(Path(filedir, "config.json")): "",
        }
    )

    tgt = imports_rule_runner.get_target(Address(filedir, target_name="t"))

    result = imports_rule_runner.request(
        PythonSourceAnalysis, (PythonImportDependenciesInferenceFieldSet.create(tgt),)
    )

    assert result
    assert len(result.identified.imports) == 6
    assert (
        len([i for i in result.identified.imports.values() if i.weak]) == 1
    ), "did not find the weak import"
    assert len(result.identified.assets) == 1
    assert (
        result.resolved.assets[str(Path(filedir, "config.json"))].status
        == ImportOwnerStatus.unambiguous
    )

    # possible owners
    assert result.resolved.resolve_results["watchdog"].status == ImportOwnerStatus.unowned
    assert result.possible_owners.value["watchdog"]
