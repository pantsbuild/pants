# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Tuple

from pants.backend.python.lint.mypy.subsystem import MyPy
from pants.backend.python.rules import (
    download_pex_bin,
    inject_init,
    pex,
    pex_from_targets,
    python_sources,
)
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.rules.python_sources import (
    UnstrippedPythonSources,
    UnstrippedPythonSourcesRequest,
    prepare_unstripped_python_sources,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import PythonSources
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.engine.addresses import Addresses
from pants.engine.fs import (
    Digest,
    FileContent,
    InputFilesContent,
    MergeDigests,
    PathGlobs,
    Snapshot,
)
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import FieldSetWithOrigin, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class MyPyFieldSet(FieldSetWithOrigin):
    required_fields = (PythonSources,)

    sources: PythonSources


class MyPyRequest(LintRequest):
    field_set_type = MyPyFieldSet


def generate_args(mypy: MyPy, *, file_list_path: str) -> Tuple[str, ...]:
    args = []
    if mypy.config:
        args.append(f"--config-file={mypy.config}")
    args.extend(mypy.args)
    args.append(f"@{file_list_path}")
    return tuple(args)


# MyPy searches for types for a package in packages containing a `py.types` marker file or else in
# a sibling `<package>-stubs` package as per PEP-0561. Going further than that PEP, MyPy restricts
# its search to `site-packages`. Since PEX deliberately isolates itself from `site-packages` as
# part of its raison d'être, we monkey-patch `site.getsitepackages` to look inside the scrubbed
# PEX sys.path before handing off to `mypy`.
#
# As a complication, MyPy does its own validation to ensure packages aren't both available in
# site-packages and on the PYTHONPATH. As such, we elide all PYTHONPATH entries from artificial
# site-packages we set up since MyPy will manually scan PYTHONPATH outside this PEX to find
# packages.
#
# See:
#   https://mypy.readthedocs.io/en/stable/installed_packages.html#installed-packages
#   https://www.python.org/dev/peps/pep-0561/#stub-only-packages
LAUNCHER_FILE = FileContent(
    "__pants_mypy_launcher.py",
    dedent(
        """\
        import os
        import runpy
        import site
        import sys
        PYTHONPATH = frozenset(
            os.path.realpath(p)
            for p in os.environ.get('PYTHONPATH', '').split(os.pathsep)
        )
        site.getsitepackages = lambda: [
            p for p in sys.path if os.path.realpath(p) not in PYTHONPATH
        ]
        runpy.run_module('mypy', run_name='__main__')
        """
    ).encode(),
)


# TODO(#10131): Improve performance, e.g. by leveraging the MyPy cache.
# TODO(#10131): Support plugins and type stubs.
@rule(desc="Lint using MyPy")
async def mypy_lint(
    request: MyPyRequest,
    mypy: MyPy,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResults:
    if mypy.skip:
        return LintResults()

    transitive_targets_request = Get(
        TransitiveTargets, Addresses(fs.address for fs in request.field_sets)
    )
    launcher_file_request = Get(Digest, InputFilesContent([LAUNCHER_FILE]))
    transitive_targets, launcher_file = await MultiGet(
        transitive_targets_request, launcher_file_request
    )

    prepared_sources_request = Get(
        UnstrippedPythonSources, UnstrippedPythonSourcesRequest(transitive_targets.closure),
    )
    mypy_pex_request = Get(
        Pex,
        PexRequest(
            output_filename="mypy.pex",
            requirements=PexRequirements(mypy.get_requirement_specs()),
            # NB: This only determines what MyPy is run with. The user can specify what version
            # their code is with `--python-version`. See
            # https://mypy.readthedocs.io/en/stable/config_file.html#platform-configuration. We do
            # not auto-configure this for simplicity and to avoid Pants magically setting values for
            # users.
            interpreter_constraints=PexInterpreterConstraints(mypy.default_interpreter_constraints),
            sources=launcher_file,
        ),
    )
    requirements_pex_request = Get(
        Pex,
        PexFromTargetsRequest(
            addresses=Addresses(fs.address for fs in request.field_sets),
            output_filename="requirements.pex",
            include_source_files=False,
        ),
    )
    runner_pex_request = Get(
        Pex,
        PexRequest(
            output_filename="mypy_runner.pex",
            interpreter_constraints=PexInterpreterConstraints(mypy.default_interpreter_constraints),
            entry_point=PurePath(LAUNCHER_FILE.path).stem,
            additional_args=(
                "--pex-path",
                ":".join(
                    (
                        mypy_pex_request.subject.output_filename,
                        requirements_pex_request.subject.output_filename,
                    )
                ),
            ),
        ),
    )
    config_snapshot_request = Get(
        Snapshot,
        PathGlobs(
            globs=[mypy.config] if mypy.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--mypy-config`",
        ),
    )
    prepared_sources, mypy_pex, requirements_pex, runner_pex, config_snapshot = await MultiGet(
        prepared_sources_request,
        mypy_pex_request,
        requirements_pex_request,
        runner_pex_request,
        config_snapshot_request,
    )

    file_list_path = "__files.txt"
    python_files = "\n".join(f for f in prepared_sources.snapshot.files if f.endswith(".py"))
    file_list = await Get(
        Digest, InputFilesContent([FileContent(file_list_path, python_files.encode())]),
    )

    merged_input_files = await Get(
        Digest,
        MergeDigests(
            [
                file_list,
                prepared_sources.snapshot.digest,
                mypy_pex.digest,
                requirements_pex.digest,
                runner_pex.digest,
                config_snapshot.digest,
            ]
        ),
    )

    process = runner_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=runner_pex.output_filename,
        pex_args=generate_args(mypy, file_list_path=file_list_path),
        input_digest=merged_input_files,
        env={"PEX_EXTRA_SYS_PATH": ":".join(prepared_sources.source_roots)},
        description=f"Run MyPy on {pluralize(len(prepared_sources.snapshot.files), 'file')}.",
    )
    result = await Get(FallibleProcessResult, Process, process)
    return LintResults([LintResult.from_fallible_process_result(result, linter_name="MyPy")])


def rules():
    return [
        mypy_lint,
        prepare_unstripped_python_sources,
        SubsystemRule(MyPy),
        UnionRule(LintRequest, MyPyRequest),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *inject_init.rules(),
        *pex.rules(),
        *pex_from_targets.rules(),
        *python_sources.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
