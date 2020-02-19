# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional, Tuple

from pants.backend.python.lint.docformatter.subsystem import Docformatter
from pants.backend.python.lint.python_format_target import PythonFormatTarget
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
from pants.engine.fs import Digest, DirectoriesToMerge
from pants.engine.isolated_process import (
  ExecuteProcessRequest,
  ExecuteProcessResult,
  FallibleExecuteProcessResult,
)
from pants.engine.legacy.structs import TargetAdaptorWithOrigin
from pants.engine.rules import UnionRule, rule, subsystem_rule
from pants.engine.selectors import Get
from pants.python.python_setup import PythonSetup
from pants.rules.core import find_target_source_files, strip_source_roots
from pants.rules.core.find_target_source_files import (
  FindTargetSourceFilesRequest,
  TargetSourceFiles,
)
from pants.rules.core.fmt import FmtResult
from pants.rules.core.lint import LintResult


@dataclass(frozen=True)
class DocformatterTarget:
  adaptor_with_origin: TargetAdaptorWithOrigin
  prior_formatter_result_digest: Optional[Digest] = None  # unused by `lint`


@dataclass(frozen=True)
class SetupRequest:
  target: DocformatterTarget
  check_only: bool


@dataclass(frozen=True)
class Setup:
  process_request: ExecuteProcessRequest


def generate_args(
  *, source_files: TargetSourceFiles, docformatter: Docformatter, check_only: bool
) -> Tuple[str, ...]:
  return (
    "--check" if check_only else "--in-place",
    *docformatter.options.args,
    *sorted(source_files.snapshot.files),
  )


@rule
async def setup(
  request: SetupRequest,
  docformatter: Docformatter,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> Setup:
  adaptor_with_origin = request.target.adaptor_with_origin
  adaptor = adaptor_with_origin.adaptor

  requirements_pex = await Get[Pex](
    CreatePex(
      output_filename="docformatter.pex",
      requirements=PexRequirements(requirements=tuple(docformatter.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(
        constraint_set=tuple(docformatter.default_interpreter_constraints)
      ),
      entry_point=docformatter.get_entry_point(),
    )
  )

  # NB: We populate the chroot with every source file belonging to the target, but possibly only
  # tell Docformatter to run over some of those files when given file arguments.
  full_sources_digest = (
    request.target.prior_formatter_result_digest or adaptor.sources.snapshot.directory_digest
  )
  specified_source_files = await Get[TargetSourceFiles](
    FindTargetSourceFilesRequest(adaptor_with_origin)
  )

  merged_input_files = await Get[Digest](
    DirectoriesToMerge(directories=(full_sources_digest, requirements_pex.directory_digest))
  )

  process_request = requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path="./docformatter.pex",
    pex_args=generate_args(
      source_files=specified_source_files, docformatter=docformatter, check_only=request.check_only
    ),
    input_files=merged_input_files,
    # NB: Even if the user specified to only run on certain files belonging to the target, we
    # still capture in the output all of the source files.
    output_files=adaptor.sources.snapshot.files,
    description=f"Run docformatter for {adaptor.address.reference()}",
  )
  return Setup(process_request)


@rule(name="Format Python docstrings with docformatter")
async def fmt(docformatter_target: DocformatterTarget, docformatter: Docformatter) -> FmtResult:
  if docformatter.options.skip:
    return FmtResult.noop()
  setup = await Get[Setup](SetupRequest(docformatter_target, check_only=False))
  result = await Get[ExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
  return FmtResult.from_execute_process_result(result)


@rule(name="Lint Python docstrings with docformatter")
async def lint(docformatter_target: DocformatterTarget, docformatter: Docformatter) -> LintResult:
  if docformatter.options.skip:
    return LintResult.noop()
  setup = await Get[Setup](SetupRequest(docformatter_target, check_only=True))
  result = await Get[FallibleExecuteProcessResult](ExecuteProcessRequest, setup.process_request)
  return LintResult.from_fallible_execute_process_result(result)


def rules():
  return [
    setup,
    fmt,
    lint,
    subsystem_rule(Docformatter),
    UnionRule(PythonFormatTarget, DocformatterTarget),
    UnionRule(PythonLintTarget, DocformatterTarget),
    *download_pex_bin.rules(),
    *find_target_source_files.rules(),
    *pex.rules(),
    *python_native_code.rules(),
    *strip_source_roots.rules(),
    *subprocess_environment.rules(),
  ]
