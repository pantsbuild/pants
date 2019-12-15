# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import math
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple, TypeVar

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
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult, FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import RootRule, console_rule, optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
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


_T = TypeVar('_T')


class _ParallelismStrategy(Enum):
  files_per_worker = 'files-per-worker'
  worker_count = 'worker-count'
  none = 'none'

  @staticmethod
  def _split_by_files_per_worker(parameter: int, all_sources: List[_T]) -> List[List[_T]]:
    return [
      all_sources[i:i + parameter]
      for i in range(0, len(all_sources), parameter)
    ]

  @staticmethod
  def _split_by_worker_count(parameter: int, all_sources: List[_T]) -> List[List[_T]]:
    sources_iterator = iter(all_sources)
    return [
      list(itertools.islice(sources_iterator, 0, math.ceil(len(all_sources) / parameter)))
      for _ in range(0, parameter)
    ]

  def split_inputs(self, parameter: int, all_sources: Iterable[_T]) -> List[List[_T]]:
    all_sources = list(all_sources)
    return self.match({
      _ParallelismStrategy.files_per_worker: lambda: self._split_by_files_per_worker(parameter, all_sources),
      _ParallelismStrategy.worker_count: lambda: self._split_by_worker_count(parameter, all_sources),
      _ParallelismStrategy.none: lambda: [all_sources],
    })()

  def make_parallelism(self, parameter: int) -> '_Parallelism':
    return _Parallelism(self, parameter)


@dataclass(frozen=True)
class _Parallelism:
  strategy: _ParallelismStrategy
  parameter: int

  def split_inputs(self, all_sources: Iterable[_T]) -> List[List[_T]]:
    return self.strategy.split_inputs(self.parameter, all_sources)


@dataclass(frozen=True)
class ScalaFmtRequest:
  config_file: Optional[SingleFile]
  input_files: FileCollection
  scalafmt_tool: ScalaFmtNativeImage
  parallelism: _Parallelism


@dataclass(frozen=True)
class ScalaFmtExeRequest:
  exe_reqs: Tuple[ExecuteProcessRequest, ...]


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

  all_argvs_outputs: List[Tuple[List[str], List[str]]] = [
    ([
      str(req.scalafmt_tool.exe.file_path),
      *prefix_args,
      *inputs,
    ], inputs)
    for inputs in req.parallelism.split_inputs(all_input_file_strs)
  ]

  return ScalaFmtExeRequest(tuple(ExecuteProcessRequest(
    argv=tuple(argv),
    input_files=merged_input,
    description=f'Execute scalafmt for {len(outputs)} sources!',
    # TODO: some sort of macro or wrapper for:
    # 1. where output files and input files are the same,
    # 2. checking that the resulting Snapshot can be wrapped in a FileCollection,
    # 3. and that the output files from expanding the digest match the input files!
    output_files=tuple(outputs),
  ) for argv, outputs in all_argvs_outputs))


@dataclass(frozen=True)
class ScalaFmtFormatRequest:
  hts: HydratedTargets
  parallelism: _Parallelism


@rule
async def make_scalafmt_request(req: ScalaFmtFormatRequest, scalafmt: ScalaFmtSubsystem) -> ScalaFmtRequest:
  scala_libraries = [ht for ht in req.hts if ht.adaptor.type_alias == 'scala_library']
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
    parallelism=req.parallelism,
  )


@dataclass(frozen=True)
class ScalaFmtResult:
  edited_files: FileCollection
  failure_exit_codes: Tuple[int, ...]
  stdout: bytes
  stderr: bytes


@rule
async def execute_scalafmt(req: ScalaFmtExeRequest) -> ScalaFmtResult:
  exe_results = await MultiGet(Get[FallibleExecuteProcessResult](ExecuteProcessRequest, exe_req)
                               for exe_req in req.exe_reqs)
  merged_output_files = await Get[Digest](DirectoriesToMerge(tuple(
    r.output_directory_digest for r in exe_results
  )))
  catted_stdout = b''.join(r.stdout for r in exe_results)
  catted_stderr = b''.join(r.stderr for r in exe_results)
  snapshotted_output = await Get[Snapshot](Digest, merged_output_files)
  return ScalaFmtResult(
    FileCollection(snapshotted_output),
    failure_exit_codes=tuple(r.exit_code for r in exe_results if r.exit_code != 0),
    stdout=catted_stdout,
    stderr=catted_stderr)


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

  if options.values.files_per_worker is not None:
    parallelism = _ParallelismStrategy.files_per_worker.make_parallelism(options.values.files_per_worker)
  elif options.values.worker_count is not None:
    parallelism = _ParallelismStrategy.worker_count.make_parallelism(options.values.worker_count)
  else:
    parallelism = _ParallelismStrategy.none.make_parallelism(0)

  result = await Get[ScalaFmtResult](ScalaFmtFormatRequest(hts, parallelism))
  console.print_stderr(f'formatted {len(result.edited_files.file_paths)} files!')
  joined_exit_codes = ', '.join(str(rc) for rc in result.failure_exit_codes)
  console.print_stderr(f'failed worker exit codes: [{joined_exit_codes}]')
  console.print_stderr(f'scalafmt stdout:')
  # Ensure the only stdout we write is the same stdout as scalafmt itself, to be pipeline-friendly.
  console.print_stdout(result.stdout.decode('utf-8'))
  console.print_stderr(f'scalafmt stderr:')
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
    RootRule(ScalaFmtFormatRequest),
    make_scalafmt_request,
    RootRule(ScalaFmtExeRequest),
    execute_scalafmt,
    scalafmt_v2,
  ]
