# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Optional

from pants.backend.jvm.subsystems.scalafmt import ScalaFmtSubsystem
from pants.binaries.binary_tool import BinaryToolFetchRequest
from pants.engine.console import Console
from pants.engine.fs import (
  Digest,
  DirectoriesToMerge,
  DirectoryToMaterialize,
  FileCollection,
  ManyFileCollections,
  PathGlobs,
  SingleFile,
  Snapshot,
  Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import RootRule, console_rule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.option.custom_types import dir_option
from pants.util.collections import Enum


@dataclass(frozen=True)
class ScalaFmtNativeImage:
  exe: SingleFile


@rule
async def extract_scalafmt_native_image(scalafmt: ScalaFmtSubsystem) -> ScalaFmtNativeImage:
  zipped_snapshot = await Get[SingleFile](BinaryToolFetchRequest(scalafmt))
  output_file = os.path.join(scalafmt.unzipped_inner_dir_platform_specific_name, 'scalafmt')
  # TODO: create some class "HackyLocalExecuteProcessRequest" which automatically adds the PATH to
  # the `env`, and uses
  # `unsafe_local_only_files_because_we_favor_speed_over_correctness_for_this_rule`!
  unzipped_result = await Get[ExecuteProcessResult](ExecuteProcessRequest(
    argv=('unzip', str(zipped_snapshot.file_path)),
    input_files=zipped_snapshot.digest,
    description=f'Unzip the scalafmt native-image version {scalafmt.version()} from its release zip.',
    output_files=(output_file,),
    env={'PATH': os.environ['PATH']},
  ))
  chmod_plus_x_result = await Get[ExecuteProcessResult](ExecuteProcessRequest(
    argv=('chmod', '+x', output_file),
    input_files=unzipped_result.output_directory_digest,
    description=f'Mark the scalafmt native-image version {scalafmt.version()} as executable!',
    output_files=(output_file,),
    env={'PATH': os.environ['PATH']},
  ))
  output_file = await Get[Snapshot](Digest, chmod_plus_x_result.output_directory_digest)
  return ScalaFmtNativeImage(SingleFile(output_file))


@dataclass(frozen=True)
class ScalaFmtRequest:
  config_file: Optional[SingleFile]
  input_files: FileCollection
  scalafmt_tool: ScalaFmtNativeImage


@dataclass(frozen=True)
class ScalaFmtExeRequest:
  exe_req: ExecuteProcessRequest


@rule
async def make_scalafmt_exe_req(req: ScalaFmtRequest, scalafmt: ScalaFmtSubsystem) -> ScalaFmtExeRequest:
  # Format the files.
  prefix_args = ['-i']

  digests_to_merge = [req.scalafmt_tool.exe.digest, req.input_files.digest]

  if scalafmt.configuration:
    config_file = SingleFile(await Get[Snapshot](PathGlobs([str(scalafmt.configuration)])))
    digests_to_merge.append(config_file.digest)
    prefix_args.extend(['--config', str(config_file.file_path)])

  merged_input = await Get[Digest](DirectoriesToMerge(tuple(digests_to_merge)))

  all_input_file_strs = [str(f) for f in req.input_files.file_paths]
  argv = [
    str(req.scalafmt_tool.exe.file_path),
    *prefix_args,
    *all_input_file_strs,
  ]

  return ScalaFmtExeRequest(ExecuteProcessRequest(
    argv=tuple(argv),
    input_files=merged_input,
    description=f'Execute scalafmt for {len(all_input_file_strs)} sources!',
    # TODO: some sort of macro or wrapper for:
    # 1. where output files and input files are the same,
    # 2. checking that the resulting Snapshot can be wrapped in a FileCollection,
    # 3. and that the output files from expanding the digest match the input files!
    output_files=tuple(all_input_file_strs),
  ))


@rule
async def make_scalafmt_request(hts: HydratedTargets, scalafmt: ScalaFmtSubsystem) -> ScalaFmtRequest:
  scala_libraries = [ht for ht in hts if ht.adaptor.type_alias == 'scala_library']
  merged_source_files = await Get[FileCollection](ManyFileCollections(
    FileCollection(ht.adaptor.sources.snapshot) for ht in scala_libraries))

  maybe_config_path = scalafmt.configuration
  maybe_config_file = None
  if maybe_config_path is not None:
    maybe_config_file = SingleFile(await Get[Snapshot](PathGlobs([str(maybe_config_path)])))

  assert scalafmt.use_native_image
  scalafmt_tool = await Get[ScalaFmtNativeImage](ScalaFmtSubsystem, scalafmt)
  return ScalaFmtRequest(
    config_file=maybe_config_file,
    input_files=merged_source_files,
    scalafmt_tool=scalafmt_tool,
  )


@dataclass(frozen=True)
class ScalaFmtResult:
  edited_files: FileCollection
  stdout: bytes
  stderr: bytes


@rule
async def execute_scalafmt(req: ScalaFmtExeRequest) -> ScalaFmtResult:
  exe_res = await Get[ExecuteProcessResult](ExecuteProcessRequest, req.exe_req)
  snapshotted_output = await Get[Snapshot](Digest, exe_res.output_directory_digest)
  return ScalaFmtResult(
    FileCollection(snapshotted_output),
    stdout=exe_res.stdout,
    stderr=exe_res.stderr)


class ScalaFmtOptions(GoalSubsystem):
  """???"""
  name = 'scalafmt-v2'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--output-dir', type=dir_option, default=None, fingerprint=False,
             help='If specified, write formatted scala files into this directory '
                  'instead of overwriting the source files in the buildroot.')

    register('--files-per-worker', type=int, fingerprint=False,
             default=None,
             help='Number of files to use per each scalafmt execution.')
    register('--worker-count', type=int, fingerprint=False,
             default=None,
             help='Total number of parallel scalafmt threads or processes to run.')


class ScalaFmt(Goal):
  subsystem_cls = ScalaFmtOptions


@console_rule
async def scalafmt_v2(
    console: Console,
    hts: HydratedTargets,
    workspace: Workspace,
    options: ScalaFmtOptions,
) -> ScalaFmt:
  result = await Get[ScalaFmtResult](HydratedTargets, hts)
  console.print_stderr(f'formatted {len(result.edited_files.file_paths)} files!')
  console.print_stderr(f'scalafmt stdout:\n')
  # Ensure the only stdout we write is the same stdout as scalafmt itself, to be pipeline-friendly.
  console.print_stdout(result.stdout.decode('utf-8'))
  console.print_stderr(f'scalafmt stderr:\n')
  console.print_stderr(result.stderr.decode('utf-8'))

  workspace.materialize_directory(DirectoryToMaterialize(
    directory_digest=result.edited_files.digest,
    path_prefix=(options.values.output_dir or ''),
  ))

  return ScalaFmt(exit_code=0)


def rules():
  return [
    optionable_rule(ScalaFmtSubsystem),
    extract_scalafmt_native_image,
    make_scalafmt_exe_req,
    make_scalafmt_request,
    RootRule(ScalaFmtExeRequest),
    execute_scalafmt,
    scalafmt_v2,
  ]
