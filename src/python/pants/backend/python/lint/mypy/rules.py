# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath
from textwrap import dedent
from typing import Tuple

from pants.backend.python.lint.mypy.subsystem import MyPy
from pants.backend.python.rules import download_pex_bin, importable_python_sources, pex
from pants.backend.python.rules.importable_python_sources import ImportablePythonSources
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
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
from pants.engine.target import FieldSetWithOrigin, Targets, TransitiveTargets
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


# MyPy searches for types for a package in packages containing a `py.types` arker file or else in
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
# TODO(#10131): Support first-party plugins.
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

    prepared_sources_request = Get(ImportablePythonSources, Targets(transitive_targets.closure))
    pex_request = Get(
        Pex,
        PexRequest(
            output_filename="mypy.pex",
            requirements=PexRequirements(mypy.get_requirement_specs()),
            # TODO(#10131): figure out how to robustly handle interpreter constraints. Unlike other
            #  linters, the version of Python used to run MyPy can be different than the version of
            #  the code.
            interpreter_constraints=PexInterpreterConstraints(mypy.default_interpreter_constraints),
            entry_point=PurePath(LAUNCHER_FILE.path).stem,
            sources=launcher_file,
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
    prepared_sources, pex, config_snapshot = await MultiGet(
        prepared_sources_request, pex_request, config_snapshot_request
    )

    file_list_path = "__files.txt"
    file_list = await Get(
        Digest,
        InputFilesContent(
            [FileContent(file_list_path, "\n".join(prepared_sources.snapshot.files).encode())]
        ),
    )

    merged_input_files = await Get(
        Digest,
        MergeDigests(
            [file_list, prepared_sources.snapshot.digest, pex.digest, config_snapshot.digest]
        ),
    )

    address_references = ", ".join(sorted(tgt.address.spec for tgt in transitive_targets.closure))
    process = pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=pex.output_filename,
        pex_args=generate_args(mypy, file_list_path=file_list_path),
        input_digest=merged_input_files,
        description=(
            f"Run MyPy on {pluralize(len(transitive_targets.closure), 'target')}: "
            f"{address_references}."
        ),
    )
    result = await Get(FallibleProcessResult, Process, process)
    return LintResults([LintResult.from_fallible_process_result(result, linter_name="MyPy")])


def rules():
    return [
        mypy_lint,
        SubsystemRule(MyPy),
        UnionRule(LintRequest, MyPyRequest),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *importable_python_sources.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
