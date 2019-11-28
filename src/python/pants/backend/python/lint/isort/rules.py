# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.targets.formattable_python_target import FormattablePythonTarget
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import (
  ExecuteProcessRequest,
  ExecuteProcessResult,
  FallibleExecuteProcessResult,
)
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult


@dataclass(frozen=True)
class IsortSetup:
  requirements_pex: Pex
  config_snapshot: Snapshot


@rule
async def setup_isort(isort: Isort) -> IsortSetup:
  config_path = isort.get_options().config
  config_snapshot = await Get[Snapshot](PathGlobs(include=(config_path,)))
  requirements_pex = await Get[Pex](
    CreatePex(
      output_filename="isort.pex",
      requirements=PexRequirements(requirements=tuple(isort.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(
        constraint_set=tuple(isort.default_interpreter_constraints)
      ),
      entry_point=isort.get_entry_point(),
    )
  )
  return IsortSetup(requirements_pex=requirements_pex, config_snapshot=config_snapshot)


@dataclass(frozen=True)
class IsortArgs:
  args: Tuple[str, ...]

  @staticmethod
  def create(*, wrapped_target: FormattablePythonTarget, check_only: bool) -> "IsortArgs":
    # NB: isort auto-discovers config files. There is no way to hardcode them via command line
    # flags. So long as the files are in the Pex's input files, isort will use the config.
    files = wrapped_target.target.sources.snapshot.files
    pex_args = []
    if check_only:
      pex_args.append("--check-only")
    pex_args.extend(files)
    return IsortArgs(tuple(pex_args))


@rule
async def create_isort_request(
  wrapped_target: FormattablePythonTarget,
  isort_args: IsortArgs,
  isort_setup: IsortSetup,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> ExecuteProcessRequest:
  target = wrapped_target.target
  merged_input_files = await Get[Digest](
    DirectoriesToMerge(
      directories=(
        target.sources.snapshot.directory_digest,
        isort_setup.requirements_pex.directory_digest,
        isort_setup.config_snapshot.directory_digest,
      )
    ),
  )
  return isort_setup.requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path="./isort.pex",
    pex_args=isort_args.args,
    input_files=merged_input_files,
    output_files=target.sources.snapshot.files,
    description=f'Run isort for {target.address.reference()}',
  )


@rule(name="Format using isort")
async def fmt(wrapped_target: FormattablePythonTarget) -> FmtResult:
  args = IsortArgs.create(wrapped_target=wrapped_target, check_only=False)
  request = await Get[ExecuteProcessRequest](IsortArgs, args)
  result = await Get[ExecuteProcessResult](ExecuteProcessRequest, request)
  return FmtResult.from_execute_process_result(result)


@rule(name="Lint using isort")
async def lint(wrapped_target: FormattablePythonTarget) -> LintResult:
  args = IsortArgs.create(wrapped_target=wrapped_target, check_only=True)
  request = await Get[ExecuteProcessRequest](IsortArgs, args)
  result = await Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  return LintResult.from_fallible_execute_process_result(result)


def rules():
  return [setup_isort, create_isort_request, fmt, lint, optionable_rule(Isort)]
