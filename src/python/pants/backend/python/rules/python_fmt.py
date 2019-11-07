# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Set, Tuple

from pants.backend.python.rules.pex import (
  CreatePex,
  Pex,
  PexInterpreterConstraints,
  PexRequirements,
)
from pants.backend.python.subsystems.black import Black
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import (
  ExecuteProcessRequest,
  ExecuteProcessResult,
  FallibleExecuteProcessResult,
)
from pants.engine.legacy.structs import (
  PantsPluginAdaptor,
  PythonAppAdaptor,
  PythonBinaryAdaptor,
  PythonTargetAdaptor,
  PythonTestsAdaptor,
)
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.rules.core.fmt import FmtResult, TargetWithSources
from pants.rules.core.lint import LintResult


# Note: this is a workaround until https://github.com/pantsbuild/pants/issues/8343 is addressed
# We have to write this type which basically represents a union of all various kinds of targets
# containing python files so we can have one single type used as an input in the run_black rule.
@dataclass(frozen=True)
class FormattablePythonTarget:
  target: Any


@dataclass(frozen=True)
class BlackInput:
  config_path: Path
  resolved_requirements_pex: Pex
  merged_input_files: Digest


@rule
def get_black_input(
  wrapped_target: FormattablePythonTarget,
  black: Black,
  ) -> BlackInput:
  config_path = black.get_options().config
  config_snapshot = yield Get(Snapshot, PathGlobs(include=(config_path,)))

  resolved_requirements_pex = yield Get(
    Pex, CreatePex(
      output_filename="black.pex",
      requirements=PexRequirements(requirements=tuple(black.get_requirement_specs())),
      interpreter_constraints=PexInterpreterConstraints(constraint_set=tuple(black.default_interpreter_constraints)),
      entry_point=black.get_entry_point(),
    )
  )
  target = wrapped_target.target
  sources_digest = target.sources.snapshot.directory_digest

  all_input_digests = [
    sources_digest,
    resolved_requirements_pex.directory_digest,
    config_snapshot.directory_digest,
  ]
  merged_input_files = yield Get(
    Digest,
    DirectoriesToMerge(directories=tuple(all_input_digests)),
  )
  yield BlackInput(config_path, resolved_requirements_pex, merged_input_files)


def _generate_black_pex_args(files: Set[str], config_path: str, *, check_only: bool) -> Tuple[str, ...]:
  # The exclude option from Black only works on recursive invocations,
  # so call black with the directories in which the files are present
  # and passing the full file names with the include option
  dirs: Set[str] = set()
  for filename in files:
    dirs.add(f"{Path(filename).parent}")
  pex_args= tuple(sorted(dirs))
  if check_only:
    pex_args += ("--check", )
  if config_path:
    pex_args += ("--config", config_path)
  if files:
    pex_args += ("--include", "|".join(re.escape(f) for f in files))
  return pex_args


def _generate_black_request(
  wrapped_target: FormattablePythonTarget,
  black_input: BlackInput,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
  *,
  check_only: bool,
  ):
  target = wrapped_target.target
  pex_args = _generate_black_pex_args(target.sources.snapshot.files, black_input.config_path, check_only = check_only)

  request = black_input.resolved_requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path="./black.pex",
    pex_args=pex_args,
    input_files=black_input.merged_input_files,
    output_files=target.sources.snapshot.files,
    description=f'Run Black for {target.address.reference()}',
  )
  return request


@rule
def fmt_with_black(
  wrapped_target: FormattablePythonTarget,
  black_input: BlackInput,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
  ) -> FmtResult:

  request = _generate_black_request(wrapped_target, black_input, python_setup, subprocess_encoding_environment, check_only = False)

  result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, request)

  yield FmtResult(
    digest=result.output_directory_digest,
    stdout=result.stdout.decode(),
    stderr=result.stderr.decode(),
  )


@rule
def lint_with_black(
  wrapped_target: FormattablePythonTarget,
  black_input: BlackInput,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
  ) -> LintResult:

  request = _generate_black_request(wrapped_target, black_input, python_setup, subprocess_encoding_environment, check_only = True)

  result = yield Get(FallibleExecuteProcessResult, ExecuteProcessRequest, request)

  yield LintResult(
    exit_code=result.exit_code,
    stdout=result.stdout.decode(),
    stderr=result.stderr.decode(),
  )


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def target_adaptor(target: PythonTargetAdaptor) -> FormattablePythonTarget:
  yield FormattablePythonTarget(target)


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def app_adaptor(target: PythonAppAdaptor) -> FormattablePythonTarget:
  yield FormattablePythonTarget(target)


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> FormattablePythonTarget:
  yield FormattablePythonTarget(target)


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def tests_adaptor(target: PythonTestsAdaptor) -> FormattablePythonTarget:
  yield FormattablePythonTarget(target)


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> FormattablePythonTarget:
  yield FormattablePythonTarget(target)


def rules():
  return [
    target_adaptor,
    app_adaptor,
    binary_adaptor,
    tests_adaptor,
    plugin_adaptor,
    get_black_input,
    fmt_with_black,
    lint_with_black,
    UnionRule(TargetWithSources, PythonTargetAdaptor),
    UnionRule(TargetWithSources, PythonAppAdaptor),
    UnionRule(TargetWithSources, PythonBinaryAdaptor),
    UnionRule(TargetWithSources, PythonTestsAdaptor),
    UnionRule(TargetWithSources, PantsPluginAdaptor),
    optionable_rule(Black),
    optionable_rule(PythonSetup),
  ]
