# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.lint.python_linter import PythonLinter
from pants.backend.python.rules import download_pex_bin, hermetic_pex, pex, prepare_chrooted_python_sources
from pants.backend.python.rules.pex import (
    CreatePex,
    Pex,
    PexInterpreterConstraints,
    PexRequirements,
)
from pants.backend.python.rules.prepare_chrooted_python_sources import ChrootedPythonSources
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.build_graph.address import Address
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get, MultiGet
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.rules.core import determine_source_files, strip_source_roots
from pants.rules.core.determine_source_files import LegacySpecifiedSourceFilesRequest, SourceFiles
from pants.rules.core.lint import Linter, LintResult


@dataclass(frozen=True)
class PylintLinter(PythonLinter):
    pass


def generate_args(*, specified_source_files: SourceFiles, pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.options.config is not None:
        args.append(f"--rcfile={pylint.options.config}")
    args.extend(pylint.options.args)
    args.extend(sorted(specified_source_files.snapshot.files))
    return tuple(args)


@rule(name="Lint using Pylint")
async def lint(
    linter: PylintLinter,
    pylint: Pylint,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
    if pylint.options.skip:
        return LintResult.noop()

    adaptors_with_origins = linter.adaptors_with_origins

    # Pylint needs direct dependencies in the chroot to ensure that imports are valid. However, it
    # doesn't lint those direct dependencies nor does it care about transitive dependencies.
    hydrated_targets = [
        HydratedTarget(adaptor_with_origin.adaptor) for adaptor_with_origin in adaptors_with_origins
    ]
    dependencies = await MultiGet(
        Get[HydratedTarget](Address, dependency)
        for dependency in itertools.chain.from_iterable(
            ht.adaptor.dependencies for ht in hydrated_targets
        )
    )
    chrooted_python_sources = await Get[ChrootedPythonSources](
        HydratedTargets([*hydrated_targets, *dependencies])
    )

    # NB: Pylint output depends upon which Python interpreter version it's run with. We ensure that
    # each target runs with its own interpreter constraints. See
    # http://pylint.pycqa.org/en/latest/faq.html#what-versions-of-python-is-pylint-supporting.
    interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
        (adaptor_with_origin.adaptor for adaptor_with_origin in adaptors_with_origins),
        python_setup=python_setup,
    )
    requirements_pex = await Get[Pex](
        CreatePex(
            output_filename="pylint.pex",
            requirements=PexRequirements(pylint.get_requirement_specs()),
            interpreter_constraints=interpreter_constraints,
            entry_point=pylint.get_entry_point(),
        )
    )

    config_path: Optional[str] = pylint.options.config
    config_snapshot = await Get[Snapshot](
        PathGlobs(
            globs=tuple([config_path] if config_path else []),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--pylint-config`",
        )
    )

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                requirements_pex.directory_digest,
                config_snapshot.directory_digest,
                chrooted_python_sources.snapshot.directory_digest,
            )
        ),
    )

    specified_source_files = await Get[SourceFiles](
        LegacySpecifiedSourceFilesRequest(adaptors_with_origins, strip_source_roots=True)
    )

    address_references = ", ".join(
        sorted(
            adaptor_with_origin.adaptor.address.reference()
            for adaptor_with_origin in adaptors_with_origins
        )
    )

    request = requirements_pex.create_hermetic_pex_request(ExecuteProcessRequest(
        argv=generate_args(specified_source_files=specified_source_files, pylint=pylint),
        input_files=merged_input_files,
        description=f"Run Pylint for {address_references}",
    ))
    result = await Get[FallibleExecuteProcessResult](HermeticPexRequest, request)
    return LintResult.from_fallible_execute_process_result(result)


def rules():
    return [
        lint,
        subsystem_rule(Pylint),
        UnionRule(Linter, PylintLinter),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *prepare_chrooted_python_sources.rules(),
        *strip_source_roots.rules(),
        *python_native_code.rules(),
        *subprocess_environment.rules(),
    ]
