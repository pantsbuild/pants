# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple, cast

from pants.backend.python.lint.bandit.subsystem import Bandit
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import PythonInterpreterCompatibility, PythonSources
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.core.util_rules.determine_source_files import (
    AllSourceFilesRequest,
    SourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.engine.fs import Digest, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, named_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import FieldSetWithOrigin
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class BanditFieldSet(FieldSetWithOrigin):
    required_fields = (PythonSources,)

    sources: PythonSources
    compatibility: PythonInterpreterCompatibility


class BanditRequest(LintRequest):
    field_set_type = BanditFieldSet


def generate_args(*, specified_source_files: SourceFiles, bandit: Bandit) -> Tuple[str, ...]:
    args = []
    if bandit.options.config is not None:
        args.append(f"--config={bandit.options.config}")
    args.extend(bandit.options.args)
    args.extend(specified_source_files.files)
    return tuple(args)


@named_rule(desc="Lint using Bandit")
async def bandit_lint(
    request: BanditRequest,
    bandit: Bandit,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResults:
    if bandit.options.skip:
        return LintResults()

    # NB: Bandit output depends upon which Python interpreter version it's run with. See
    # https://github.com/PyCQA/bandit#under-which-version-of-python-should-i-install-bandit.
    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (field_set.compatibility for field_set in request.field_sets), python_setup=python_setup
    ) or PexInterpreterConstraints(bandit.default_interpreter_constraints)
    requirements_pex_request = Get[Pex](
        PexRequest(
            output_filename="bandit.pex",
            requirements=PexRequirements(bandit.get_requirement_specs()),
            interpreter_constraints=interpreter_constraints,
            entry_point=bandit.get_entry_point(),
        )
    )

    config_path: Optional[str] = bandit.options.config
    config_snapshot_request = Get[Snapshot](
        PathGlobs(
            globs=[config_path] if config_path else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--bandit-config`",
        )
    )

    all_source_files_request = Get[SourceFiles](
        AllSourceFilesRequest(field_set.sources for field_set in request.field_sets)
    )
    specified_source_files_request = Get[SourceFiles](
        SpecifiedSourceFilesRequest(
            (field_set.sources, field_set.origin) for field_set in request.field_sets
        )
    )

    requirements_pex, config_snapshot, all_source_files, specified_source_files = cast(
        Tuple[Pex, Snapshot, SourceFiles, SourceFiles],
        await MultiGet(
            [
                requirements_pex_request,
                config_snapshot_request,
                all_source_files_request,
                specified_source_files_request,
            ]
        ),
    )

    input_digest = await Get[Digest](
        MergeDigests(
            (all_source_files.snapshot.digest, requirements_pex.digest, config_snapshot.digest)
        )
    )

    address_references = ", ".join(
        sorted(field_set.address.reference() for field_set in request.field_sets)
    )

    process = requirements_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./bandit.pex",
        pex_args=generate_args(specified_source_files=specified_source_files, bandit=bandit),
        input_digest=input_digest,
        description=f"Run Bandit on {pluralize(len(request.field_sets), 'target')}: {address_references}.",
    )
    result = await Get[FallibleProcessResult](Process, process)
    return LintResults([LintResult.from_fallible_process_result(result, linter_name="Bandit")])


def rules():
    return [
        bandit_lint,
        SubsystemRule(Bandit),
        UnionRule(LintRequest, BanditRequest),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
