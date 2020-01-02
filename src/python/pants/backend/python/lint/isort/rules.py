# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import List, Optional, Tuple

from pants.backend.python.lint.isort.subsystem import Isort
from pants.backend.python.lint.python_format_target import PythonFormatTarget
from pants.backend.python.lint.python_lint_target import PythonLintTarget
from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import (
  ExecuteProcessRequest,
  ExecuteProcessResult,
  FallibleExecuteProcessResult,
)
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult


@dataclass(frozen=True)
class IsortTarget:
  target: TargetAdaptor
  prior_formatter_result_digest: Optional[Digest] = None  # unused by `lint`


@dataclass(frozen=True)
class IsortSetup:
  requirements_pex: Pex
  config_snapshot: Snapshot
  passthrough_args: Tuple[str, ...]


@rule
async def setup_isort(isort: Isort) -> IsortSetup:
  config_path: Optional[List[str]] = isort.get_options().config
  config_snapshot = await Get[Snapshot](PathGlobs(include=config_path or ()))
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
  return IsortSetup(
    requirements_pex=requirements_pex,
    config_snapshot=config_snapshot,
    passthrough_args=isort.get_args(),
  )


@dataclass(frozen=True)
class IsortArgs:
  args: Tuple[str, ...]

  @staticmethod
  def create(
    *, wrapped_target: IsortTarget, isort_setup: IsortSetup, check_only: bool,
  ) -> "IsortArgs":
    # NB: isort auto-discovers config files. There is no way to hardcode them via command line
    # flags. So long as the files are in the Pex's input files, isort will use the config.
    files = wrapped_target.target.sources.snapshot.files
    pex_args = []
    if check_only:
      pex_args.append("--check-only")
    if isort_setup.passthrough_args:
      pex_args.extend(isort_setup.passthrough_args)
    pex_args.extend(files)
    return IsortArgs(tuple(pex_args))


@rule
async def create_isort_request(
  wrapped_target: IsortTarget,
  isort_args: IsortArgs,
  isort_setup: IsortSetup,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> ExecuteProcessRequest:
  target = wrapped_target.target
  sources_digest = wrapped_target.prior_formatter_result_digest or target.sources.snapshot.directory_digest
  merged_input_files = await Get[Digest](
    DirectoriesToMerge(
      directories=(
        sources_digest,
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
async def fmt(wrapped_target: IsortTarget, isort_setup: IsortSetup) -> FmtResult:
  args = IsortArgs.create(wrapped_target=wrapped_target, isort_setup=isort_setup, check_only=False)
  request = await Get[ExecuteProcessRequest](IsortArgs, args)
  result = await Get[ExecuteProcessResult](ExecuteProcessRequest, request)
  return FmtResult.from_execute_process_result(result)


@rule(name="Lint using isort")
async def lint(wrapped_target: IsortTarget, isort_setup: IsortSetup) -> LintResult:
  args = IsortArgs.create(wrapped_target=wrapped_target, isort_setup=isort_setup, check_only=True)
  request = await Get[ExecuteProcessRequest](IsortArgs, args)
  result = await Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  return LintResult.from_fallible_execute_process_result(result)


def rules():
  return [
    setup_isort,
    create_isort_request,
    fmt,
    lint,
    optionable_rule(Isort),
    UnionRule(PythonFormatTarget, IsortTarget),
    UnionRule(PythonLintTarget, IsortTarget),
  ]
