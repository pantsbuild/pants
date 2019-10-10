# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Set

from pants.backend.python.rules.pex import CreatePex, Pex, PexInterpreterContraints, PexRequirements
from pants.backend.python.subsystems.black import Black
from pants.backend.python.subsystems.grey import Grey, GreyPatchDigest
from pants.backend.python.subsystems.python_formatter import PythonFormatter, PythonFormattingTool
from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.engine.fs import Digest, DirectoriesToMerge, PathGlobs, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.structs import (
  PantsPluginAdaptor,
  PythonAppAdaptor,
  PythonBinaryAdaptor,
  PythonTargetAdaptor,
  PythonTestsAdaptor,
)
from pants.engine.rules import UnionRule, optionable_rule, rule
from pants.engine.selectors import Get, Params
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.rules.core.fmt import FmtResult, FmtTarget


# Note: this is a workaround until https://github.com/pantsbuild/pants/issues/8343 is addressed
# We have to write this type which basically represents a union of all various kinds of targets
# containing python files so we can have one single type used as an input in the run_black rule.
@dataclass(frozen=True)
class FormattablePythonTarget:
    target: Any


@rule
def run_black(
  wrapped_target: FormattablePythonTarget,
  grey_patch: GreyPatchDigest,
  python_formatter: PythonFormatter,
  options_bootstrapper: OptionsBootstrapper,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
  ) -> FmtResult:
  tool = python_formatter.get_options().tool
  if tool == PythonFormattingTool.black:
    formatter = yield Get(Black, OptionsBootstrapper, options_bootstrapper)
    entry_point = formatter.get_entry_point()
    patch_digest = None
  elif tool == PythonFormattingTool.black_with_two_spaces_indent:
    formatter = yield Get(Grey, OptionsBootstrapper, options_bootstrapper)
    entry_point = grey_patch.entry_point
    patch_digest = grey_patch.digest

  config_path = formatter.get_options().config
  config_snapshot = yield Get(Snapshot, PathGlobs(include=(config_path,)))

  resolved_requirements_pex = yield Get(
    Pex, CreatePex(
      output_filename="python_formatter.pex",
      requirements=PexRequirements(requirements=tuple(formatter.get_requirement_specs())),
      interpreter_constraints=PexInterpreterContraints(constraint_set=frozenset(formatter.default_interpreter_constraints)),
      entry_point=entry_point,
      input_files_digest=patch_digest,
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

  # The exclude option from Black only works on recursive invocations,
  # so call black with the directories in which the files are present
  # and passing the full file names with the include option
  dirs: Set[str] = set()
  for filename in target.sources.snapshot.files:
    dirs.add(f"{Path(filename).parent}")
  pex_args= tuple(sorted(dirs))
  if config_path:
    pex_args += ("--config", config_path)
  if target.sources.snapshot.files:
    pex_args += ("--include", "|".join(re.escape(f) for f in target.sources.snapshot.files))

  request = resolved_requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path="./python_formatter.pex",
    pex_args=pex_args,
    input_files=merged_input_files,
    output_files=target.sources.snapshot.files,
    description=f'Run Black for {target.address.reference()}',
  )

  result = yield Get(ExecuteProcessResult, ExecuteProcessRequest, request)

  yield FmtResult(
    digest=result.output_directory_digest,
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
    run_black,
    UnionRule(FmtTarget, PythonTargetAdaptor),
    UnionRule(FmtTarget, PythonAppAdaptor),
    UnionRule(FmtTarget, PythonBinaryAdaptor),
    UnionRule(FmtTarget, PythonTestsAdaptor),
    UnionRule(FmtTarget, PantsPluginAdaptor),
    optionable_rule(PythonFormatter),
    optionable_rule(Black),
    optionable_rule(Grey),
    optionable_rule(PythonSetup),
  ]
