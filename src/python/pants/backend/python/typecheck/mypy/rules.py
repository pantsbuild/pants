# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.rules import download_pex_bin, inject_ancestor_files, inject_init, pex
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.rules.python_sources import (
    UnstrippedPythonSources,
    UnstrippedPythonSourcesRequest,
    prepare_unstripped_python_sources,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import PythonSources
from pants.backend.python.typecheck.mypy.subsystem import MyPy
from pants.core.goals.typecheck import TypecheckRequest, TypecheckResult, TypecheckResults
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests, PathGlobs, Snapshot
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


class MyPyRequest(TypecheckRequest):
    field_set_type = MyPyFieldSet


def generate_args(mypy: MyPy, *, file_list_path: str) -> Tuple[str, ...]:
    args = []
    if mypy.config:
        args.append(f"--config-file={mypy.config}")
    args.extend(mypy.args)
    args.append(f"@{file_list_path}")
    return tuple(args)


# TODO(#10131): Improve performance, e.g. by leveraging the MyPy cache.
# TODO(#10131): Support plugins and type stubs.
@rule(desc="Lint using MyPy")
async def mypy_lint(
    request: MyPyRequest,
    mypy: MyPy,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> TypecheckResults:
    if mypy.skip:
        return TypecheckResults()

    transitive_targets = await Get(
        TransitiveTargets, Addresses(fs.address for fs in request.field_sets)
    )

    prepared_sources_request = Get(
        UnstrippedPythonSources, UnstrippedPythonSourcesRequest(transitive_targets.closure),
    )
    pex_request = Get(
        Pex,
        PexRequest(
            output_filename="mypy.pex",
            distributed_to_users=False,
            requirements=PexRequirements(mypy.get_requirement_specs()),
            # NB: This only determines what MyPy is run with. The user can specify what version
            # their code is with `--python-version`. See
            # https://mypy.readthedocs.io/en/stable/config_file.html#platform-configuration. We do
            # not auto-configure this for simplicity and to avoid Pants magically setting values for
            # users.
            interpreter_constraints=PexInterpreterConstraints(mypy.default_interpreter_constraints),
            entry_point=mypy.get_entry_point(),
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
    python_files = "\n".join(f for f in prepared_sources.snapshot.files if f.endswith(".py"))
    file_list_digest = await Get(
        Digest, CreateDigest([FileContent(file_list_path, python_files.encode())]),
    )

    merged_input_files = await Get(
        Digest,
        MergeDigests(
            [file_list_digest, prepared_sources.snapshot.digest, pex.digest, config_snapshot.digest]
        ),
    )

    process = pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=pex.output_filename,
        pex_args=generate_args(mypy, file_list_path=file_list_path),
        input_digest=merged_input_files,
        env={"PEX_EXTRA_SYS_PATH": ":".join(prepared_sources.source_roots)},
        description=f"Run MyPy on {pluralize(len(prepared_sources.snapshot.files), 'file')}.",
    )
    result = await Get(FallibleProcessResult, Process, process)
    return TypecheckResults(
        [TypecheckResult.from_fallible_process_result(result, typechecker_name="MyPy")]
    )


def rules():
    return [
        mypy_lint,
        prepare_unstripped_python_sources,
        SubsystemRule(MyPy),
        UnionRule(TypecheckRequest, MyPyRequest),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *inject_ancestor_files.rules(),
        *inject_init.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
