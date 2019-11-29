# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from dataclasses import dataclass
from typing import Tuple

from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.tasks.coursier.coursier_subsystem import CoursierSubsystem
from pants.backend.jvm.tasks.coursier_resolve import CoursierMixin
from pants.binaries.binary_tool import BinaryToolFetchRequest
from pants.engine.fs import Digest, FilesContent, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.rules import RootRule, optionable_rule, rule
from pants.engine.selectors import Get
from pants.java.jar.jar_dependency import JarDependency
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir


@dataclass(frozen=True)
class ResolvedCoursier:
  snapshot: Snapshot


@rule
async def snapshot_coursier(coursier: CoursierSubsystem) -> ResolvedCoursier:
  snapshot = await Get[Snapshot](BinaryToolFetchRequest(tool=coursier))
  return ResolvedCoursier(snapshot)


# TODO: we currently expect the jar dependencies to be provided directly in a JarResolveRequest,
# *without* using JarDependencyManagement#targets_by_artifact_set(), which implies that
# global_excludes is always on and we don't make use of IvyUtils.calculate_classpath()! See
# CoursierMixin#resolve() for the missing pieces.
@dataclass(frozen=True)
class JarResolveRequest:
  jar_deps: Tuple[JarDependency, ...]


@dataclass(frozen=True)
class CoursierResolveRequest:
  exe_req: ExecuteProcessRequest

  _json_output_path = './out.json'


@rule
def generate_coursier_execution_request(
    coursier: CoursierSubsystem,
    resolved_coursier: ResolvedCoursier,
    manager: JarDependencyManagement,
    jar_req: JarResolveRequest,
) -> CoursierResolveRequest:
  jars_to_resolve, pinned_coords = CoursierMixin._compute_jars_to_resolve_and_pin(
    raw_jars=jar_req.jar_deps,
    artifact_set=None,
    manager=manager,
  )
  common_args = coursier.common_args()

  # TODO: figure out a cleaner way for CoursierMixin._construct_cmd_args() to make use of the
  # `coursier_workdir` arg!
  with temporary_dir(cleanup=False) as workdir:
    cmd_args = CoursierMixin._construct_cmd_args(
      jars=jars_to_resolve,
      common_args=common_args,
      global_excludes=True,
      pinned_coords=pinned_coords,
      coursier_workdir=workdir,
      json_output_path=CoursierResolveRequest._json_output_path)

  exe_req = ExecuteProcessRequest(
    argv=tuple([
      './jdk/bin/java',
      '-cp', ':'.join(
        resolved_coursier.snapshot.files +
        resolved_coursier.snapshot.dirs
      ),
      'coursier.cli.Coursier',
    ] + cmd_args),
    input_files=resolved_coursier.snapshot.directory_digest,
    description=f'Call coursier to resolve jars {jar_req}.',
    output_files=tuple([CoursierResolveRequest._json_output_path]),
    is_nailgunnable=True,
  )

  return CoursierResolveRequest(exe_req)


@dataclass(frozen=True)
class ResolvedCoursierJar:
  coord: str
  unsafe_local_file_path: str
  dependency_coords: Tuple[str, ...]


@dataclass(frozen=True)
class CoursierResolveResult:
  resolved_jars: Tuple[ResolvedCoursierJar, ...]


@rule
async def execute_coursier(req: CoursierResolveRequest) -> CoursierResolveResult:
  # TODO: stream stdout/stderr to console somehow!
  result = await Get[ExecuteProcessResult](ExecuteProcessRequest, req.exe_req)
  output_file = assert_single_element(
    await Get[FilesContent](Digest, result.output_directory_digest))
  assert output_file.path == CoursierResolveRequest._json_output_path
  parsed_output = json.loads(output_file.content)

  return CoursierResolveResult(tuple([
    ResolvedCoursierJar(
      coord=dep['coord'],
      unsafe_local_file_path=dep['file'],
      dependency_coords=dep['dependencies'],
    )
    for dep in parsed_output['dependencies']
  ]))


@dataclass(frozen=True)
class SnapshottedResolveResult:
  merged_snapshot: Snapshot


@rule
def snapshotted_coursier_result(res: CoursierResolveResult) -> SnapshottedResolveResult:
  # TODO: snapshot things that may be outside of the buildroot (the cached coursier jar deps!!!!)
  return None


def rules():
  return [
    optionable_rule(CoursierSubsystem),
    snapshot_coursier,
    optionable_rule(JarDependencyManagement),
    RootRule(JarResolveRequest),
    generate_coursier_execution_request,
    execute_coursier,
    snapshotted_coursier_result,
  ]
