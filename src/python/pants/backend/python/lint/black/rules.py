# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from pants.backend.python.lint.black.subsystem import Black
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
class BlackSetup:
  """This abstraction is used to deduplicate the implementations for the `fmt` and `lint` rules,
  which only differ in whether or not to append `--check` to the Black CLI args."""
  config_path: Optional[Path]
  resolved_requirements_pex: Pex
  merged_input_files: Digest

  def generate_pex_arg_list(self, *, files: Tuple[str, ...], check_only: bool) -> Tuple[str, ...]:
    pex_args = []
    if check_only:
      pex_args.append("--check")
    if self.config_path is not None:
      pex_args.extend(["--config", self.config_path])
    # NB: For some reason, Black's --exclude option only works on recursive invocations, meaning
    # calling Black on a directory(s) and letting it auto-discover files. However, we don't want
    # Black to run over everything recursively under the directory of our target, as Black should
    # only touch files in the target's `sources`. We can use `--include` to ensure that Black only
    # operates on the files we actually care about.
    pex_args.extend(["--include", "|".join(re.escape(f) for f in files)])
    pex_args.extend(str(Path(f).parent) for f in files)
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
      pex_path="./black.pex",
      pex_args=self.generate_pex_arg_list(
        files=target.sources.snapshot.files, check_only=check_only
      ),
      input_files=self.merged_input_files,
      output_files=target.sources.snapshot.files,
      description=f'Run Black for {target.address.reference()}',
    )


@rule
async def setup_black(wrapped_target: FormattablePythonTarget, black: Black) -> BlackSetup:
  config_path: Optional[str] = black.get_options().config
  config_snapshot = await Get(Snapshot, PathGlobs(include=(config_path,)))
  resolved_requirements_pex = await Get(
    Pex, CreatePex(
      output_filename="black.pex",
      requirements=PexRequirements(requirements=tuple(black.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(
        constraint_set=tuple(black.default_interpreter_constraints)
      ),
      entry_point=black.get_entry_point(),
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
  return BlackSetup(config_path, resolved_requirements_pex, merged_input_files)


@rule(name="Format using black")
async def fmt(
  wrapped_target: FormattablePythonTarget,
  black_setup: BlackSetup,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> FmtResult:
  request = black_setup.create_execute_request(
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


@rule(name="Lint using black")
async def lint(
  wrapped_target: FormattablePythonTarget,
  black_setup: BlackSetup,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
  request = black_setup.create_execute_request(
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
    setup_black,
    fmt,
    lint,
    optionable_rule(Black),
    optionable_rule(PythonSetup),
  ]
