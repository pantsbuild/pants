# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals.lockfile import GeneratePythonLockfile
from pants.backend.python.lint.import_linter import skip_field
from pants.backend.python.lint.import_linter.subsystem import (
    ImportLinterCustomContracts,
    ImportLinterLockfileSentinel,
)
from pants.backend.python.lint.import_linter.subsystem import rules as subsystem_rules
from pants.backend.python.target_types import PythonRequirementTarget, PythonSourcesGeneratorTarget
from pants.backend.python.util_rules import python_sources
from pants.core.target_types import GenericTarget
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.ordered_set import FrozenOrderedSet


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *subsystem_rules(),
            *skip_field.rules(),
            *python_sources.rules(),
            *target_types_rules.rules(),
            QueryRule(ImportLinterCustomContracts, []),
            QueryRule(GeneratePythonLockfile, [ImportLinterLockfileSentinel]),
        ],
        target_types=[PythonSourcesGeneratorTarget, GenericTarget, PythonRequirementTarget],
    )


def test_custom_contracts(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                python_requirement(name='import-linter', requirements=['import-linter==1.2.7'])
                python_requirement(name='colors', requirements=['ansicolors'])
                """
            ),
            "import-contracts/subdir1/util.py": "",
            "import-contracts/subdir1/BUILD": "python_sources(dependencies=['import-contracts/subdir2'])",
            "import-contracts/subdir2/another_util.py": "",
            "import-contracts/subdir2/BUILD": "python_sources()",
            "import-contracts/contract.py": "",
            "import-contracts/BUILD": dedent(
                """\
                python_sources(
                    dependencies=['//:import-linter', '//:colors', 'import-contracts/subdir1']
                )
                """
            ),
        }
    )
    rule_runner.set_options(
        [
            "--source-root-patterns=import-contracts",
            "--import-linter-source-plugins=import-contracts/contract.py",
        ],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    custom_contracts = rule_runner.request(ImportLinterCustomContracts, [])
    assert custom_contracts.requirement_strings == FrozenOrderedSet(
        ["ansicolors", "import-linter==1.2.7"]
    )
    assert (
        custom_contracts.sources_digest
        == rule_runner.make_snapshot(
            {
                "import-contracts/contract.py": "",
                "import-contracts/subdir1/util.py": "",
                "import-contracts/subdir2/another_util.py": "",
            }
        ).digest
    )
    assert custom_contracts.source_roots == ("import-contracts",)
