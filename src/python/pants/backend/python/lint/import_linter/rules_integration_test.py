# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.lint.import_linter.rules import (
    ImportLinterPartitions,
    ImportLinterRequest,
)
from pants.backend.python.lint.import_linter.rules import rules as import_linter_rules
from pants.backend.python.lint.import_linter.subsystem import ImportLinter, ImportLinterFieldSet
from pants.backend.python.lint.import_linter.subsystem import rules as import_linter_subsystem_rules
from pants.backend.python.target_types import (
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
    PythonSourceTarget,
)
from pants.build_graph.address import Address
from pants.core.goals.lint import LintResult, LintResults
from pants.core.util_rules import config_files
from pants.engine.rules import QueryRule
from pants.engine.target import Target
from pants.testutil.python_interpreter_selection import all_major_minor_python_versions
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *import_linter_rules(),
            *import_linter_subsystem_rules(),
            *config_files.rules(),
            *target_types_rules.rules(),
            QueryRule(LintResults, (ImportLinterRequest,)),
            QueryRule(ImportLinterPartitions, (ImportLinterRequest,)),
        ],
        target_types=[PythonSourcesGeneratorTarget, PythonRequirementTarget, PythonSourceTarget],
        preserve_tmpdirs=True,
    )


def run_import_linter(
    rule_runner: RuleRunner, targets: list[Target], *, extra_args: list[str] | None = None
) -> tuple[LintResult, ...]:
    rule_runner.set_options(
        ["--backend-packages=pangs.backend.python.lint.import_linter", *(extra_args or ())],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    result = rule_runner.request(
        LintResults, [ImportLinterRequest(ImportLinterFieldSet.create(tgt) for tgt in targets)]
    )
    return result.results


CONFIG_BASE = """[importlinter]
root_packages=
    one
    two
    three
include_external_packages = True
"""

FORBIDDEN_CONTRACT = """
[importlinter:contract:1]
name = Forbidden Contract
type = forbidden
source_modules =
    one
forbidden_modules =
    two
    three.foo
"""

INDEPENDENCE_CONTRACT = """
[importlinter:contract:2]
name = Independence Contract
type = independence
modules =
    one
    two
"""

LAYERS_CONTRACT = """
[importlinter:contract:3]
name = Layers Contract
type = layers
layers =
    three.bar
    three
"""


@pytest.mark.platform_specific_behavior
@pytest.mark.parametrize(
    "major_minor_interpreter",
    all_major_minor_python_versions(ImportLinter.default_interpreter_constraints),
)
def test_passing(rule_runner: RuleRunner, major_minor_interpreter: str) -> None:
    rule_runner.write_files(
        {
            ".importlinter": f"{CONFIG_BASE}\n{FORBIDDEN_CONTRACT}\n{INDEPENDENCE_CONTRACT}\n{LAYERS_CONTRACT}",
            "one/BUILD": "python_sources()",
            "one/__init__.py": "import three.bar",
            "two/BUILD": "python_sources()",
            "two/__init__.py": "",
            "three/BUILD": "python_sources()",
            "three/__init__.py": "",
            "three/foo.py": "import one",
            "three/bar.py": "import three",
        }
    )
    tgts = [
        rule_runner.get_target(Address("one", relative_file_path="__init__.py")),
        rule_runner.get_target(Address("three", relative_file_path="foo.py")),
    ]
    result = run_import_linter(
        rule_runner,
        tgts,
        extra_args=[f"--import-linter-interpreter-constraints=['=={major_minor_interpreter}.*']"],
    )
    assert len(result) == 1
    assert result[0].exit_code == 0
