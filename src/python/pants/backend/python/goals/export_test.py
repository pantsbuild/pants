# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import re
import sys
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import export
from pants.backend.python.goals.export import ExportVenvsRequest
from pants.backend.python.target_types import PythonRequirementTarget
from pants.backend.python.util_rules import pex_from_targets
from pants.base.specs import RawSpecs, RecursiveGlobSpec
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
            QueryRule(Targets, [RawSpecs]),
            QueryRule(ExportResults, [ExportVenvsRequest]),
        ],
        target_types=[PythonRequirementTarget],
    )


@pytest.mark.parametrize("enable_resolves", [False, True])
@pytest.mark.parametrize("symlink", [False, True])
def test_export_venv_pipified(
    rule_runner: RuleRunner,
    enable_resolves: bool,
    symlink: bool,
) -> None:
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

    symlink_flag = f"--{'' if symlink else 'no-'}export-symlink-python-virtualenv"
    rule_runner.set_options(
        [
            f"--python-interpreter-constraints=['=={current_interpreter}']",
            "--python-resolves={'a': 'lock.txt', 'b': 'lock.txt'}",
            f"--python-enable-resolves={enable_resolves}",
            # Turn off lockfile validation to make the test simpler.
            "--python-invalid-lockfile-behavior=ignore",
            symlink_flag,
        ],
        env_inherit={"PATH", "PYENV_ROOT"},
    )
    targets = rule_runner.request(
        Targets,
        [RawSpecs(recursive_globs=(RecursiveGlobSpec("src/foo"),), description_of_origin="tests")],
    )
    all_results = rule_runner.request(ExportResults, [ExportVenvsRequest(targets)])

    for result, resolve in zip(all_results, ["a", "b"] if enable_resolves else [""]):
        if symlink:
            assert len(result.post_processing_cmds) == 1
            ppc0 = result.post_processing_cmds[0]
            assert ppc0.argv[0:2] == ("ln", "-s")
            # The third arg is the full path to the venv under the pex_root, which we
            # don't easily know here, so we ignore it in this comparison.
            assert ppc0.argv[3] == os.path.join("{digest_root}", current_interpreter)
            assert ppc0.extra_env == FrozenDict()
        else:
            assert len(result.post_processing_cmds) == 2

            ppc0 = result.post_processing_cmds[0]
            # The first arg is the full path to the python interpreter, which we
            # don't easily know here, so we ignore it in this comparison.

            # The second arg is expected to be tmpdir/./pex.
            tmpdir, pex_pex_name = os.path.split(os.path.normpath(ppc0.argv[1]))
            assert pex_pex_name == "pex"
            assert re.match(r"\{digest_root\}/\.[0-9a-f]{32}\.tmp", tmpdir)

            # The third arg is expected to be tmpdir/requirements.pex.
            req_pex_dir, req_pex_name = os.path.split(ppc0.argv[2])
            assert req_pex_dir == tmpdir
            assert req_pex_name == "requirements.pex"

            assert ppc0.argv[3:] == (
                "venv",
                "--pip",
                "--collisions-ok",
                f"{{digest_root}}/{current_interpreter}",
            )
            assert ppc0.extra_env["PEX_MODULE"] == "pex.tools"
            assert ppc0.extra_env.get("PEX_ROOT") is not None

            ppc1 = result.post_processing_cmds[1]
            assert ppc1.argv == ("rm", "-rf", tmpdir)
            assert ppc1.extra_env == FrozenDict()

    reldirs = [result.reldir for result in all_results]
    if enable_resolves:
        assert reldirs == [
            "python/virtualenvs/a",
            "python/virtualenvs/b",
        ]
    else:
        assert reldirs == ["python/virtualenv"]
