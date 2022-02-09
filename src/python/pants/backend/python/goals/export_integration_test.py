# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import sys

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import export
from pants.backend.python.goals.export import ExportVenvRequest
from pants.backend.python.target_types import PythonRequirementTarget
from pants.backend.python.util_rules import pex_from_targets
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.goals.export import ExportResults
from pants.engine.rules import QueryRule
from pants.engine.target import Targets
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *export.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            QueryRule(Targets, [AddressSpecs]),
            QueryRule(ExportResults, [ExportVenvRequest]),
        ],
        target_types=[PythonRequirementTarget],
    )


def test_export_venv(rule_runner: RuleRunner) -> None:
    # We know that the current interpreter exists on the system.
    vinfo = sys.version_info
    current_interpreter = f"{vinfo.major}.{vinfo.minor}.{vinfo.micro}"

    rule_runner.set_options(
        [f"--python-interpreter-constraints=['=={current_interpreter}']"],
        env_inherit={"PATH", "PYENV_ROOT"},
    )
    rule_runner.write_files(
        {"src/foo/BUILD": "python_requirement(name='req', requirements=['ansicolors==1.1.8'])"}
    )
    targets = rule_runner.request(Targets, [AddressSpecs([DescendantAddresses("src/foo")])])
    all_results = rule_runner.request(ExportResults, [ExportVenvRequest(targets)])
    assert len(all_results) == 1
    data = all_results[0]

    assert len(data.symlinks) == 1
    symlink = data.symlinks[0]
    assert symlink.link_rel_path == current_interpreter
    assert "named_caches/pex_root/venvs/" in symlink.source_path
