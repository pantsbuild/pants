# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import sys
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import export
from pants.backend.python.goals.export import ExportVenvsRequest
from pants.backend.python.target_types import PythonRequirementTarget
from pants.backend.python.util_rules import pex_from_targets
from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.core.goals.export import ExportResults
from pants.core.util_rules import distdir
from pants.engine.rules import QueryRule
from pants.engine.target import Targets
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *export.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            *distdir.rules(),
            QueryRule(Targets, [AddressSpecs]),
            QueryRule(ExportResults, [ExportVenvsRequest]),
        ],
        target_types=[PythonRequirementTarget],
    )


def test_export_venvs(rule_runner: RuleRunner) -> None:
    # We know that the current interpreter exists on the system.
    vinfo = sys.version_info
    current_interpreter = f"{vinfo.major}.{vinfo.minor}.{vinfo.micro}"
    rule_runner.write_files(
        {
            "src/foo/BUILD": dedent(
                """\
                python_requirement(name='req1', requirements=['ansicolors==1.1.8'], resolve='a')
                python_requirement(name='req2', requirements=['ansicolors==1.1.8'], resolve='b')
                """
            ),
            "lock.txt": "ansicolors==1.1.8",
        }
    )

    def run(enable_resolves: bool) -> ExportResults:
        rule_runner.set_options(
            [
                f"--python-interpreter-constraints=['=={current_interpreter}']",
                "--python-resolves={'a': 'lock.txt', 'b': 'lock.txt'}",
                f"--python-enable-resolves={enable_resolves}",
                # Turn off lockfile validation to make the test simpler.
                "--python-invalid-lockfile-behavior=ignore",
            ],
            env_inherit={"PATH", "PYENV_ROOT"},
        )
        targets = rule_runner.request(Targets, [AddressSpecs([DescendantAddresses("src/foo")])])
        all_results = rule_runner.request(ExportResults, [ExportVenvsRequest(targets)])

        for result in all_results:
            assert len(result.post_processing_cmds) == 2

            ppc0 = result.post_processing_cmds[0]
            assert ppc0.argv == (
                os.path.join("{digest_root}", ".", "pex"),
                os.path.join("{digest_root}", "requirements.pex"),
                "venv",
                "--pip",
                "--collisions-ok",
                "--remove=all",
                f"{{digest_root}}/{current_interpreter}",
            )
            assert ppc0.extra_env == FrozenDict({"PEX_MODULE": "pex.tools"})

            ppc1 = result.post_processing_cmds[1]
            assert ppc1.argv == (
                "rm",
                "-f",
                os.path.join("{digest_root}", ".", "pex"),
            )
            assert ppc1.extra_env == FrozenDict()

        return all_results

    resolve_results = run(enable_resolves=True)
    assert len(resolve_results) == 2
    assert {result.reldir for result in resolve_results} == {
        "python/virtualenvs/a",
        "python/virtualenvs/b",
    }

    no_resolve_results = run(enable_resolves=False)
    assert len(no_resolve_results) == 1
    assert no_resolve_results[0].reldir == "python/virtualenv"
