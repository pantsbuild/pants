# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.bandit.subsystem import Bandit
from pants.backend.python.lint.python_lint_target import PythonLintTarget
from pants.backend.python.rules import download_pex_bin, pex
from pants.backend.python.rules.pex import (
    CreatePex,
    Pex,
    PexInterpreterConstraints,
    PexRequirements,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, FallibleExecuteProcessResult
from pants.engine.legacy.structs import PythonTargetAdaptor, TargetAdaptorWithOrigin
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.rules.core import determine_specified_source_files, strip_source_roots
from pants.rules.core.determine_specified_source_files import (
    SpecifiedSourceFiles,
    SpecifiedSourceFilesRequest,
)
from pants.rules.core.lint import LintResult


@dataclass(frozen=True)
class BanditTarget:
    adaptor_with_origin: TargetAdaptorWithOrigin


def generate_args(*, source_files: SpecifiedSourceFiles, bandit: Bandit) -> Tuple[str, ...]:
    args = []
    if bandit.options.config is not None:
        args.append(f"--config={bandit.options.config}")
    args.extend(bandit.options.args)
    args.extend(sorted(source_files.snapshot.files))
    return tuple(args)


@rule(name="Lint using Bandit")
async def lint(
    bandit_target: BanditTarget,
    bandit: Bandit,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
    if bandit.options.skip:
        return LintResult.noop()

    adaptor_with_origin = bandit_target.adaptor_with_origin
    adaptor = adaptor_with_origin.adaptor

    # NB: Bandit output depends upon which Python interpreter version it's run with. We ensure that
    # each target runs with its own interpreter constraints. See
    # https://github.com/PyCQA/bandit#under-which-version-of-python-should-i-install-bandit.
    interpreter_constraints = PexInterpreterConstraints.create_from_adaptors(
        adaptors=[adaptor] if isinstance(adaptor, PythonTargetAdaptor) else [],
        python_setup=python_setup,
    )
    requirements_pex = await Get[Pex](
        CreatePex(
            output_filename="bandit.pex",
            requirements=PexRequirements(requirements=tuple(bandit.get_requirement_specs())),
            interpreter_constraints=interpreter_constraints,
            entry_point=bandit.get_entry_point(),
        )
    )

    config_path: Optional[str] = bandit.options.config
    config_snapshot = await Get[Snapshot](
        PathGlobs(
            globs=tuple([config_path] if config_path else []),
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--bandit-config`",
        )
    )

    merged_input_files = await Get[Digest](
        DirectoriesToMerge(
            directories=(
                adaptor.sources.snapshot.directory_digest,
                requirements_pex.directory_digest,
                config_snapshot.directory_digest,
            )
        ),
    )

    source_files = await Get[SpecifiedSourceFiles](
        SpecifiedSourceFilesRequest([adaptor_with_origin])
    )

    request = requirements_pex.create_execute_request(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./bandit.pex",
        pex_args=generate_args(source_files=source_files, bandit=bandit),
        input_files=merged_input_files,
        description=f"Run Bandit for {adaptor.address.reference()}",
    )
    result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, request)
    return LintResult.from_fallible_execute_process_result(result)


def rules():
    return [
        lint,
        subsystem_rule(Bandit),
        UnionRule(PythonLintTarget, BanditTarget),
        *download_pex_bin.rules(),
        *determine_specified_source_files.rules(),
        *pex.rules(),
        *python_native_code.rules(),
        *strip_source_roots.rules(),
        *subprocess_environment.rules(),
    ]
