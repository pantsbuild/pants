# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import os
import re
import sys
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import export
from pants.backend.python.goals.export import ExportVenvsRequest, PythonResolveExportFormat
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonRequirementTarget,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import local_dists_pep660, pex_from_targets
from pants.base.specs import RawSpecs
from pants.core.goals.export import ExportResults
from pants.core.util_rules import distdir
from pants.engine.internals.parametrize import Parametrize
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
            *local_dists_pep660.rules(),
            QueryRule(Targets, [RawSpecs]),
            QueryRule(ExportResults, [ExportVenvsRequest]),
        ],
        target_types=[PythonRequirementTarget, PythonSourcesGeneratorTarget, PythonDistribution],
        objects={"python_artifact": PythonArtifact, "parametrize": Parametrize},
    )


@pytest.mark.parametrize(
    "py_resolve_format",
    [
        PythonResolveExportFormat.symlinked_immutable_virtualenv,
        PythonResolveExportFormat.mutable_virtualenv,
    ],
)
def test_export_venv_new_codepath(
    rule_runner: RuleRunner,
    py_resolve_format: PythonResolveExportFormat,
) -> None:
    # We know that the current interpreter exists on the system.
    vinfo = sys.version_info
    current_interpreter = f"{vinfo.major}.{vinfo.minor}.{vinfo.micro}"
    rule_runner.write_files(
        {
            "src/foo/__init__.py": "from colors import *",
            "src/foo/BUILD": dedent(
                """\
                python_sources(name='foo', resolve=parametrize('a', 'b'))
                python_distribution(
                    name='dist',
                    provides=python_artifact(name='foo', version='1.2.3'),
                    dependencies=[':foo@resolve=a'],
                )
                python_requirement(name='req1', requirements=['ansicolors==1.1.8'], resolve='a')
                python_requirement(name='req2', requirements=['ansicolors==1.1.8'], resolve='b')
                """
            ),
            "lock.txt": "ansicolors==1.1.8",
        }
    )

    format_flag = f"--export-py-resolve-format={py_resolve_format.value}"
    rule_runner.set_options(
        [
            f"--python-interpreter-constraints=['=={current_interpreter}']",
            "--python-enable-resolves=True",
            "--python-resolves={'a': 'lock.txt', 'b': 'lock.txt'}",
            "--export-resolve=a",
            "--export-resolve=b",
            # Turn off lockfile validation to make the test simpler.
            "--python-invalid-lockfile-behavior=ignore",
            # Turn off python synthetic lockfile targets to make the test simpler.
            "--no-python-enable-lockfile-targets",
            "--export-py-editable-in-resolve=['a', 'b']",
            format_flag,
        ],
        env_inherit={"PATH", "PYENV_ROOT"},
    )
    all_results = rule_runner.request(ExportResults, [ExportVenvsRequest(targets=())])

    for result, resolve in zip(all_results, ["a", "b"]):
        if py_resolve_format == PythonResolveExportFormat.symlinked_immutable_virtualenv:
            assert len(result.post_processing_cmds) == 2
            ppc0, ppc1 = result.post_processing_cmds
            assert ppc0.argv == ("rmdir", "{digest_root}")
            assert ppc0.extra_env == FrozenDict()
            assert ppc1.argv[0:2] == ("ln", "-s")
            # The third arg is the full path to the venv under the pex_root, which we
            # don't easily know here, so we ignore it in this comparison.
            assert ppc1.argv[3] == "{digest_root}"
            assert ppc1.extra_env == FrozenDict()
        else:
            if resolve == "a":
                # editable wheels are installed for a user resolve that has dists
                assert len(result.post_processing_cmds) == 5
            else:
                # tool resolves (flake8) and user resolves w/o dists (b)
                # do not run the commands to do editable installs
                assert len(result.post_processing_cmds) == 2

            ppc0 = result.post_processing_cmds[0]
            # The first arg is the full path to the python interpreter, which we
            # don't easily know here, so we ignore it in this comparison.

            # The second arg is expected to be tmpdir/./pex.
            tmpdir, pex_pex_name = os.path.split(os.path.normpath(ppc0.argv[1]))
            assert pex_pex_name == "pex"
            assert re.match(r"\{digest_root\}/\.[0-9a-f]{32}\.tmp", tmpdir)

            # The third arg is expected to be tmpdir/{resolve}.pex.
            req_pex_dir, req_pex_name = os.path.split(ppc0.argv[2])
            assert req_pex_dir == tmpdir
            assert req_pex_name == f"{resolve}.pex"

            assert ppc0.argv[3:] == (
                "venv",
                "--pip",
                "--collisions-ok",
                "{digest_root}",
            )
            assert ppc0.extra_env["PEX_MODULE"] == "pex.tools"
            assert ppc0.extra_env.get("PEX_ROOT") is not None

            ppc1 = result.post_processing_cmds[-1]
            assert ppc1.argv == ("rm", "-rf", tmpdir)
            assert ppc1.extra_env == FrozenDict()

    reldirs = [result.reldir for result in all_results]
    assert reldirs == [
        f"python/virtualenvs/a/{current_interpreter}",
        f"python/virtualenvs/b/{current_interpreter}",
    ]
