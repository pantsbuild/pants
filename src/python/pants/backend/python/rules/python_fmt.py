# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

from pants.backend.python.rules.pex import CreatePex, Pex
from pants.backend.python.subsystems.black import Black
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
from pants.engine.selectors import Get
from pants.rules.core.fmt import FmtResult, FmtTarget
from pants.util.objects import datatype


class PythonFormatable(datatype(['target'])):
  pass


@rule
def run_black(
  target: PythonFormatable,
  black: Black,
  python_setup: PythonSetup,
  subprocess_encoding_environment: SubprocessEncodingEnvironment,
  ) -> FmtResult:
  config_path = black.get_options().config
  config_snapshot = yield Get(Snapshot, PathGlobs, PathGlobs(include=(config_path,)))

  resolved_requirements_pex = yield Get(
    Pex, CreatePex(
      output_filename="black.pex",
      requirements=tuple(black.get_requirement_specs()),
      interpreter_constraints=(),
      entry_point=black.get_entry_point(),
    )
  )
  target = target.target
  sources_digest = target.sources.snapshot.directory_digest

  all_input_digests = [
    sources_digest,
    resolved_requirements_pex.directory_digest,
    config_snapshot.directory_digest,
  ]
  merged_input_files = yield Get(
    Digest,
    DirectoriesToMerge,
    DirectoriesToMerge(directories=tuple(all_input_digests)),
  )

  # The exclude option from Black only works on recursive invocations,
  # so call black with the directories in which the files are present
  # and passing the full file names with the include option
  dirs = []
  for filename in target.sources.snapshot.files:
    dirs.append(os.path.dirname(filename))
  pex_args= tuple(dirs)
  if config_path:
    pex_args += ("--config", config_path)
  if target.sources.snapshot.files:
    pex_args += ("--include",) + target.sources.snapshot.files

  request = resolved_requirements_pex.create_execute_request(
    python_setup=python_setup,
    subprocess_encoding_environment=subprocess_encoding_environment,
    pex_path="./black.pex",
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


@rule
def target_adaptor(target: PythonTargetAdaptor) -> PythonFormatable:
  yield PythonFormatable(target)


@rule
def app_adaptor(target: PythonAppAdaptor) -> PythonFormatable:
  yield PythonFormatable(target)


@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> PythonFormatable:
  yield PythonFormatable(target)


@rule
def tests_adaptor(target: PythonTestsAdaptor) -> PythonFormatable:
  yield PythonFormatable(target)


@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> PythonFormatable:
  yield PythonFormatable(target)


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
    optionable_rule(Black),
    optionable_rule(PythonSetup),
  ]
