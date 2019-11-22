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
  """This abstraction is used to deduplicate the implementations for the `fmt` and `lint` rules,
  which only differ in whether or not to append `--check-only` to the isort CLI args."""
  resolved_requirements_pex: Pex
  merged_input_files: Digest

  @staticmethod
  def generate_pex_arg_list(*, files: Tuple[str, ...], check_only: bool) -> Tuple[str, ...]:
    pex_args = []
    if check_only:
      pex_args.append("--check-only")
    pex_args.extend(files)
    return tuple(pex_args)

  def create_execute_request(
    self,
    *,
    wrapped_target: FormattablePythonTarget,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    check_only: bool,
  ) -> ExecuteProcessRequest:
    target = wrapped_target.target
    return self.resolved_requirements_pex.create_execute_request(
      python_setup=python_setup,
      subprocess_encoding_environment=subprocess_encoding_environment,
      pex_path="./isort.pex",
      pex_args=self.generate_pex_arg_list(
        files=target.sources.snapshot.files, check_only=check_only
      ),
      input_files=self.merged_input_files,
      output_files=target.sources.snapshot.files,
      description=f'Run isort for {target.address.reference()}',
    )


@rule
async def setup_isort(wrapped_target: FormattablePythonTarget, isort: Isort) -> IsortSetup:
  # NB: isort auto-discovers config. We ensure that the config is included in the inputted files.
  config_path = isort.get_options().config
  config_snapshot = await Get(Snapshot, PathGlobs(include=(config_path,)))
  resolved_requirements_pex = await Get(
    Pex, CreatePex(
      output_filename="isort.pex",
      requirements=PexRequirements(requirements=tuple(isort.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(
        constraint_set=tuple(isort.default_interpreter_constraints)
      ),
      entry_point=isort.get_entry_point(),
    )
  )

  sources_digest = wrapped_target.target.sources.snapshot.directory_digest

  merged_input_files = await Get(
    Digest,
    DirectoriesToMerge(
      directories=(
        sources_digest,
        resolved_requirements_pex.directory_digest,
        config_snapshot.directory_digest,
      )
    ),
  )
  return IsortSetup(resolved_requirements_pex, merged_input_files)


@rule
async def fmt(
  wrapped_target: FormattablePythonTarget,
  isort_setup: IsortSetup,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> FmtResult:
  request = isort_setup.create_execute_request(
    wrapped_target=wrapped_target,
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    check_only=False
  )
  result = await Get(ExecuteProcessResult, ExecuteProcessRequest, request)
  return FmtResult(
    digest=result.output_directory_digest,
    stdout=result.stdout.decode(),
    stderr=result.stderr.decode(),
  )


@rule
async def lint(
  wrapped_target: FormattablePythonTarget,
  isort_setup: IsortSetup,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
  request = isort_setup.create_execute_request(
    wrapped_target=wrapped_target,
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    check_only=True
  )
  result = await Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)
  return LintResult(
    exit_code=result.exit_code,
    stdout=result.stdout.decode(),
    stderr=result.stderr.decode(),
  )


def rules():
  return [
    setup_isort,
    fmt,
    lint,
    optionable_rule(Isort),
    optionable_rule(PythonSetup),
  ]
