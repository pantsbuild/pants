# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple, cast

from pants.backend.python.lint.pylint.subsystem import Pylint
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
from pants.backend.python.target_types import PythonInterpreterCompatibility, PythonSources
from pants.core.goals.lint import LinterFieldSet, LinterFieldSets, LintResult
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.core.util_rules.determine_source_files import SourceFiles, SpecifiedSourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import Digest, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, named_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Dependencies, Targets
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PylintFieldSet(LinterFieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources
    dependencies: Dependencies
    compatibility: PythonInterpreterCompatibility


class PylintFieldSets(LinterFieldSets):
    field_set_type = PylintFieldSet


def generate_args(*, specified_source_files: SourceFiles, pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.options.config is not None:
        args.append(f"--rcfile={pylint.options.config}")
    args.extend(pylint.options.args)
    args.extend(sorted(specified_source_files.snapshot.files))
    return tuple(args)


@named_rule(desc="Lint using Pylint")
async def pylint_lint(
    field_sets: PylintFieldSets,
    pylint: Pylint,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
    if pylint.options.skip:
        return LintResult.noop()

    # Pylint needs direct dependencies in the chroot to ensure that imports are valid. However, it
    # doesn't lint those direct dependencies nor does it care about transitive dependencies.
    addresses = []
    for field_set in field_sets:
        addresses.append(field_set.address)
        addresses.extend(field_set.dependencies.value or ())
    targets = await Get[Targets](Addresses(addresses))

    # NB: Pylint output depends upon which Python interpreter version it's run with. We ensure that
    # each target runs with its own interpreter constraints. See
    # http://pylint.pycqa.org/en/latest/faq.html#what-versions-of-python-is-pylint-supporting.
    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (field_set.compatibility for field_set in field_sets), python_setup
    )
    requirements_pex_request = Get[Pex](
        PexRequest(
            output_filename="pylint.pex",
            requirements=PexRequirements(pylint.get_requirement_specs()),
            interpreter_constraints=interpreter_constraints,
            entry_point=pylint.get_entry_point(),
        )
    )

    config_path: Optional[str] = pylint.options.config
    config_snapshot_request = Get[Snapshot](
        PathGlobs(
            globs=tuple([config_path] if config_path else []),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--pylint-config`",
        )
    )

    prepare_python_sources_request = Get[ImportablePythonSources](Targets, targets)
    specified_source_files_request = Get[SourceFiles](
        SpecifiedSourceFilesRequest(
            ((field_set.sources, field_set.origin) for field_set in field_sets),
            strip_source_roots=True,
        )
    )

    requirements_pex, config_snapshot, prepared_python_sources, specified_source_files = cast(
        Tuple[Pex, Snapshot, ImportablePythonSources, SourceFiles],
        await MultiGet(
            [
                requirements_pex_request,
                config_snapshot_request,
                prepare_python_sources_request,
                specified_source_files_request,
            ]
        ),
    )

    input_digest = await Get[Digest](
        MergeDigests(
            (
                requirements_pex.digest,
                config_snapshot.digest,
                prepared_python_sources.snapshot.digest,
            )
        ),
    )

    address_references = ", ".join(
        sorted(field_set.address.reference() for field_set in field_sets)
    )

    process = requirements_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./pylint.pex",
        pex_args=generate_args(specified_source_files=specified_source_files, pylint=pylint),
        input_digest=input_digest,
        description=f"Run Pylint on {pluralize(len(field_sets), 'target')}: {address_references}.",
    )
    result = await Get[FallibleProcessResult](Process, process)
    return LintResult.from_fallible_process_result(result, linter_name="Pylint")


def rules():
    return [
        pylint_lint,
        SubsystemRule(Pylint),
        UnionRule(LinterFieldSets, PylintFieldSets),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *importable_python_sources.rules(),
        *strip_source_roots.rules(),
        *python_native_code.rules(),
        *subprocess_environment.rules(),
    ]
