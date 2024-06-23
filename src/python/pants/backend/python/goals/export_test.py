# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import dataclasses
import os
import re
import sys
from textwrap import dedent

import pytest

from pants.backend.python import target_types_rules
from pants.backend.python.goals import export
from pants.backend.python.goals.export import ExportVenvsRequest, PythonResolveExportFormat
from pants.backend.python.lint.isort import subsystem as isort_subsystem
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.backend.python.target_types import (
    PythonDistribution,
    PythonRequirementTarget,
    PythonResolveField,
    PythonSourceField,
    PythonSourcesGeneratorTarget,
)
from pants.backend.python.util_rules import local_dists_pep660, pex_from_targets
from pants.base.specs import RawSpecs
from pants.core.goals.export import ExportResults
from pants.core.util_rules import distdir
from pants.engine.fs import CreateDigest, DigestContents
from pants.engine.internals.native_engine import Digest, Snapshot
from pants.engine.internals.parametrize import Parametrize
from pants.engine.internals.selectors import Get
from pants.engine.rules import QueryRule, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    SingleSourceField,
    Target,
    Targets,
)
from pants.engine.unions import UnionRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner
from pants.util.frozendict import FrozenDict

pants_args_for_python_lockfiles = [
    "--python-enable-resolves=True",
    # Turn off lockfile validation to make the test simpler.
    "--python-invalid-lockfile-behavior=ignore",
    # Turn off python synthetic lockfile targets to make the test simpler.
    "--no-python-enable-lockfile-targets",
]


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *export.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            *distdir.rules(),
            *local_dists_pep660.rules(),
            *isort_subsystem.rules(),  # add a tool that we can try exporting
            QueryRule(Targets, [RawSpecs]),
            QueryRule(ExportResults, [ExportVenvsRequest]),
        ],
        target_types=[PythonRequirementTarget, PythonSourcesGeneratorTarget, PythonDistribution],
        objects={"python_artifact": PythonArtifact, "parametrize": Parametrize},
    )


@pytest.mark.parametrize(
    "py_resolve_format,py_hermetic_scripts",
    [
        (PythonResolveExportFormat.symlinked_immutable_virtualenv, True),
        (PythonResolveExportFormat.mutable_virtualenv, True),
        (PythonResolveExportFormat.mutable_virtualenv, False),
    ],
)
def test_export_venv_new_codepath(
    rule_runner: RuleRunner,
    py_resolve_format: PythonResolveExportFormat,
    py_hermetic_scripts: bool,
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
    hermetic_flags = [] if py_hermetic_scripts else ["--export-py-hermetic-scripts=false"]
    rule_runner.set_options(
        [
            *pants_args_for_python_lockfiles,
            f"--python-interpreter-constraints=['=={current_interpreter}']",
            "--python-resolves={'a': 'lock.txt', 'b': 'lock.txt'}",
            "--export-resolve=a",
            "--export-resolve=b",
            "--export-py-editable-in-resolve=['a', 'b']",
            format_flag,
            *hermetic_flags,
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

            assert ppc0.argv[3:7] == (
                "venv",
                "--pip",
                "--collisions-ok",
                f"--prompt={resolve}/{current_interpreter}",
            )
            if py_hermetic_scripts:
                assert "--non-hermetic-scripts" not in ppc0.argv
            else:
                assert ppc0.argv[7] == "--non-hermetic-scripts"
            assert ppc0.argv[-1] == "{digest_root}"
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


def test_export_tool(rule_runner: RuleRunner) -> None:
    """Test exporting an ExportableTool."""
    rule_runner.set_options([*pants_args_for_python_lockfiles, "--export-resolve=isort"])
    results = rule_runner.request(ExportResults, [ExportVenvsRequest(tuple())])
    assert len(results) == 1
    result = results[0]
    assert result.resolve == isort_subsystem.Isort.options_scope
    assert "isort" in result.description


def test_export_codegen_outputs():
    class CodegenSourcesField(SingleSourceField):
        pass

    class CodegenTarget(Target):
        alias = "codegen_target"
        core_fields = (CodegenSourcesField, PythonResolveField)
        help = "n/a"

    class CodegenGenerateSourcesRequest(GenerateSourcesRequest):
        input = CodegenSourcesField
        output = PythonSourceField

    @rule
    async def do_codegen(request: CodegenGenerateSourcesRequest) -> GeneratedSources:
        # Generate a Python file with the same contents as each input file.
        input_files = await Get(DigestContents, Digest, request.protocol_sources.digest)
        generated_files = [
            dataclasses.replace(input_file, path=input_file.path + ".py")
            for input_file in input_files
        ]
        result = await Get(Snapshot, CreateDigest(generated_files))
        return GeneratedSources(result)

    rule_runner = RuleRunner(
        rules=[
            *export.rules(),
            *pex_from_targets.rules(),
            *target_types_rules.rules(),
            *distdir.rules(),
            *local_dists_pep660.rules(),
            do_codegen,
            QueryRule(Targets, [RawSpecs]),
            QueryRule(ExportResults, [ExportVenvsRequest]),
            UnionRule(GenerateSourcesRequest, CodegenGenerateSourcesRequest),
        ],
        target_types=[
            PythonRequirementTarget,
            PythonSourcesGeneratorTarget,
            PythonDistribution,
            CodegenTarget,
        ],
    )

    vinfo = sys.version_info
    current_interpreter = f"{vinfo.major}.{vinfo.minor}.{vinfo.micro}"
    rule_runner.set_options(
        [
            *pants_args_for_python_lockfiles,
            f"--python-interpreter-constraints=['=={current_interpreter}']",
            "--python-resolves={'test-resolve': 'test-resolve.lock'}",
            "--source-root-patterns=src/python",
            "--export-resolve=test-resolve",
            "--export-py-generated-sources",
        ],
        env_inherit=PYTHON_BOOTSTRAP_ENV,
    )

    rule_runner.write_files(
        {
            "test-resolve.lock": "",
            "src/python/foo/BUILD": dedent(
                """\
            codegen_target(name="codegen", source="an-input", resolve="test-resolve")
            """
            ),
            "src/python/foo/an-input": "print('Hello World!')\n",
        }
    )

    export_results = rule_runner.request(ExportResults, [ExportVenvsRequest(targets=())])
    assert len(export_results) == 1
    export_result = export_results[0]

    export_snapshot = rule_runner.request(Snapshot, [export_result.digest])
    assert any(p.endswith("__pants_codegen__/codegen_setup.py") for p in export_snapshot.files)
    assert any(p.endswith("__pants_codegen__/foo/an-input.py") for p in export_snapshot.files)
