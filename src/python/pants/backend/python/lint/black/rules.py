# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from pants.backend.python.lint.black.subsystem import Black
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
class BlackTarget:
  target: TargetAdaptor
  prior_formatter_result_digest: Optional[Digest] = None  # unused by `lint`


@dataclass(frozen=True)
class BlackSetup:
  requirements_pex: Pex
  config_snapshot: Snapshot
  passthrough_args: Optional[Tuple[str, ...]]


@rule
async def setup_black(black: Black) -> BlackSetup:
  config_path: Optional[str] = black.get_options().config
  config_snapshot = await Get[Snapshot](PathGlobs(include=(config_path,)))
  requirements_pex = await Get[Pex](
    CreatePex(
      output_filename="black.pex",
      requirements=PexRequirements(requirements=tuple(black.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(
        constraint_set=tuple(black.default_interpreter_constraints)
      ),
      entry_point=black.get_entry_point(),
    )
  )
  return BlackSetup(
    requirements_pex=requirements_pex,
    config_snapshot=config_snapshot,
    passthrough_args=black.get_args(),
  )


@dataclass(frozen=True)
class BlackArgs:
  args: Tuple[str, ...]

  @staticmethod
  def create(
    *, wrapped_target: BlackTarget, black_setup: BlackSetup, check_only: bool,
  ) -> "BlackArgs":
    files = wrapped_target.target.sources.snapshot.files
    pex_args = []
    if check_only:
      pex_args.append("--check")
    if black_setup.config_snapshot.files:
      pex_args.extend(["--config", black_setup.config_snapshot.files[0]])
    if black_setup.passthrough_args:
      pex_args.extend(black_setup.passthrough_args)
    # NB: For some reason, Black's --exclude option only works on recursive invocations, meaning
    # calling Black on a directory(s) and letting it auto-discover files. However, we don't want
    # Black to run over everything recursively under the directory of our target, as Black should
    # only touch files in the target's `sources`. We can use `--include` to ensure that Black only
    # operates on the files we actually care about.
    pex_args.extend(["--include", "|".join(re.escape(f) for f in files)])
    pex_args.extend(str(Path(f).parent) for f in files)
    return BlackArgs(tuple(pex_args))


@rule
async def create_black_request(
  wrapped_target: BlackTarget,
  black_args: BlackArgs,
  black_setup: BlackSetup,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> ExecuteProcessRequest:
  target = wrapped_target.target
  sources_digest = wrapped_target.prior_formatter_result_digest or target.sources.snapshot.directory_digest
  merged_input_files = await Get[Digest](
    DirectoriesToMerge(
      directories=(
        sources_digest,
        black_setup.requirements_pex.directory_digest,
        black_setup.config_snapshot.directory_digest,
      )
    ),
  )
  return black_setup.requirements_pex.create_execute_request(
      python_setup=python_setup,
      subprocess_encoding_environment=subprocess_encoding_environment,
      pex_path="./black.pex",
      pex_args=black_args.args,
      input_files=merged_input_files,
      output_files=target.sources.snapshot.files,
      description=f'Run Black for {target.address.reference()}',
  )


@rule(name="Format using Black")
async def fmt(wrapped_target: BlackTarget, black_setup: BlackSetup) -> FmtResult:
  args = BlackArgs.create(black_setup=black_setup, wrapped_target=wrapped_target, check_only=False)
  request = await Get[ExecuteProcessRequest](BlackArgs, args)
  result = await Get[ExecuteProcessResult](ExecuteProcessRequest, request)
  return FmtResult.from_execute_process_result(result)


@rule(name="Lint using Black")
async def lint(wrapped_target: BlackTarget, black_setup: BlackSetup) -> LintResult:
  args = BlackArgs.create(black_setup=black_setup, wrapped_target=wrapped_target, check_only=True)
  request = await Get[ExecuteProcessRequest](BlackArgs, args)
  result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, request)
  return LintResult.from_fallible_execute_process_result(result)


def rules():
  return [
    setup_black,
    create_black_request,
    fmt,
    lint,
    optionable_rule(Black),
    UnionRule(PythonFormatTarget, BlackTarget),
    UnionRule(PythonLintTarget, BlackTarget),
  ]
