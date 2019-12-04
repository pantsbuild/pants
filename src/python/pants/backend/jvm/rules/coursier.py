# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pants.backend.jvm.rules.hermetic_dist import HermeticDist
from pants.backend.jvm.rules.jvm_options import JvmOptions
from pants.backend.jvm.subsystems.jar_dependency_management import JarDependencyManagement
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.tasks.coursier.coursier_subsystem import CoursierSubsystem
from pants.backend.jvm.tasks.coursier_resolve import CoursierMixin
from pants.base.build_root import BuildRoot
from pants.binaries.binary_tool import BinaryToolFetchRequest
from pants.build_graph.target import Target
from pants.engine.console import Console
from pants.engine.fs import (Digest, DirectoriesToMerge, FileContent, FilesContent,
                             InputFilesContent, PathGlobs, Snapshot)
from pants.engine.goal import Goal
from pants.engine.interactive_runner import InteractiveProcessRequest, InteractiveRunner
from pants.engine.isolated_process import ExecuteProcessRequest, ExecuteProcessResult
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import RootRule, console_rule, optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.util.collections import assert_single_element
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import fast_relpath
from pants.util.memo import memoized_method, memoized_property


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedCoursier:
  snapshot: Snapshot


@rule
async def snapshot_coursier(coursier: CoursierSubsystem) -> ResolvedCoursier:
  snapshot = await Get[Snapshot](BinaryToolFetchRequest(tool=coursier))
  return ResolvedCoursier(snapshot)


# TODO: we currently expect the jar dependencies to be provided directly in a JarResolveRequest,
# *without* using JarDependencyManagement#targets_by_artifact_set(), which implies that
# global_excludes is always empty and we don't make use of IvyUtils.calculate_classpath()! See
# CoursierMixin#resolve() for the missing pieces.
@dataclass(frozen=True)
class JarResolveRequest:
  hydrated_targets: Tuple[HydratedTarget, ...]
  jar_deps: Tuple[JarDependency, ...]


@dataclass(frozen=True)
class ResolveConfiguration:
  conf: str = 'default'


@dataclass(frozen=True)
class CoursierRequest:
  jar_resolution: JarResolveRequest
  jvm_options: JvmOptions = JvmOptions(())
  jar_path_base: Optional[Path] = None
  conf: ResolveConfiguration = ResolveConfiguration()

  @property
  def source_targets(self):
    return self.jar_resolution.hydrated_targets


@dataclass(frozen=True)
class CoursierExecutionRequest:
  orig_req: CoursierRequest
  exe_req: ExecuteProcessRequest

  _json_output_path = 'out.json'

  def __getattr__(self, key, **kwargs):
    """Use the prototype pattern with the original abstract coursier request."""
    if hasattr(self.orig_req, key):
      return getattr(self.orig_req, key)
    return super().__getattr__(key, **kwargs)


_LOCAL_EXCLUDES_FILENAME = 'excludes.txt'


@rule
async def generate_coursier_execution_request(
    coursier: CoursierSubsystem,
    resolved_coursier: ResolvedCoursier,
    manager: JarDependencyManagement,
    hermetic_dist: HermeticDist,
    req: CoursierRequest,
) -> CoursierExecutionRequest:
  jars_to_resolve, pinned_coords = CoursierMixin._compute_jars_to_resolve_and_pin(
    raw_jars=req.jar_resolution.jar_deps,
    artifact_set=None,
    manager=manager,
  )
  common_args = coursier.common_args()

  # TODO: figure out a cleaner way for CoursierMixin._construct_cmd_args() to make use of the
  # `coursier_workdir` arg!
  cmd_args, local_exclude_args = CoursierMixin._construct_cmd_args(
    jars=jars_to_resolve,
    common_args=common_args,
    global_excludes=[],
    pinned_coords=pinned_coords,
    coursier_workdir=None,
    json_output_path=CoursierExecutionRequest._json_output_path,
    strict_jar_revision_checking=False,
    affecting_the_local_filesystem=False,
  )

  if local_exclude_args:
    excludes_digest = await Get[Digest](InputFilesContent(tuple([FileContent(
      path=_LOCAL_EXCLUDES_FILENAME,
      content='\n'.join(local_exclude_args).encode(),
    )])))
    merged_digest = await Get[Digest](DirectoriesToMerge(tuple([
      resolved_coursier.snapshot.directory_digest,
      excludes_digest,
    ])))
    exclude_argv = '--local-exclude-file', _LOCAL_EXCLUDES_FILENAME,
  else:
    merged_digest = resolved_coursier.snapshot.directory_digest
    exclude_argv = []

  exe_req = ExecuteProcessRequest(
    argv=tuple([
      os.path.join(hermetic_dist.symbolic_home, 'bin/java'),
      '-cp', ':'.join(
        resolved_coursier.snapshot.files +
        resolved_coursier.snapshot.dirs
      ),
      *req.jvm_options.options,
      'coursier.cli.Coursier',
      *cmd_args,
      *exclude_argv,
    ]),
    input_files=merged_digest,
    description=f'Call coursier to resolve jars {req}.',
    output_files=tuple([CoursierExecutionRequest._json_output_path]),
    jdk_home=hermetic_dist.underlying_home,
    is_nailgunnable=True,
  )

  return CoursierExecutionRequest(orig_req=req, exe_req=exe_req)


@dataclass(frozen=True)
class CoursierResolveResult:
  base_conf: ResolveConfiguration
  jars_per_target: Tuple[Tuple[Target, Tuple[ResolvedJar, ...]], ...]

  @memoized_property
  def target_jars_mapping(self) -> Dict[Target, Tuple[ResolvedJar, ...]]:
    return {t: jars for t, jars in self.jars_per_target}

  @memoized_property
  def resolved_jars(self) -> List[ResolvedJar]:
    return [j for _target, jars in self.jars_per_target for j in jars]


@rule
async def execute_coursier(
    req: CoursierExecutionRequest,
    coursier: CoursierSubsystem,
    build_root: BuildRoot,
    interactive_runner: InteractiveRunner,
) -> CoursierResolveResult:

  logger.info(f'req: {req}')
  # import pdb; pdb.set_trace()

  output_digest = None
  # TODO: stream stdout/stderr to console somehow!
  if False:
    interactive_result = interactive_runner.run_local_interactive_process(InteractiveProcessRequest(
      argv=req.exe_req.argv,
      env=req.exe_req.env,
      hermetic_input=req.exe_req.input_files,
      run_in_workspace=False,
      output_file_path=CoursierExecutionRequest._json_output_path,
      jdk_home=req.exe_req.jdk_home,
    ))
    if interactive_result.process_exit_code == 0:
      output_digest = interactive_result.output_snapshot.directory_digest
  if not output_digest:
    exe_result = await Get[ExecuteProcessResult](ExecuteProcessRequest, req.exe_req)
    output_digest = exe_result.output_directory_digest

  output_file = assert_single_element(
    await Get[FilesContent](Digest, output_digest))
  assert output_file.path == CoursierExecutionRequest._json_output_path
  parsed_output = json.loads(output_file.content)

  flattened_resolution = CoursierMixin.extract_dependencies_by_root(parsed_output)

  # TODO: convert the file operations performed here into v2!
  coord_to_resolved_jars = CoursierMixin.map_coord_to_resolved_jars(
    result=parsed_output,
    coursier_cache_path=coursier.get_options().cache_dir,
    pants_jar_path_base=(req.jar_path_base or build_root.path))

  # Construct a map from org:name to the reconciled org:name:version coordinate
  # This is used when there is won't be a conflict_resolution entry because the conflict
  # was resolved in pants.
  org_name_to_org_name_rev = {}
  for coord in coord_to_resolved_jars.keys():
    org_name_to_org_name_rev[f'{coord.org}:{coord.name}'] = coord

  jars_per_target = []

  override_classifiers = CoursierMixin.override_classifiers_for_conf(req.conf.conf)

  for ht in req.source_targets:
    t = ht.adaptor
    jars_to_digest = []
    if isinstance(t.v1_target, JarLibrary):
      def get_transitive_resolved_jars(my_coord, resolved_jars):
        transitive_jar_path_for_coord = []
        coord_str = str(my_coord)
        if coord_str in flattened_resolution and my_coord in resolved_jars:
          transitive_jar_path_for_coord.append(resolved_jars[my_coord])

          for c in flattened_resolution[coord_str]:
            j = resolved_jars.get(CoursierMixin.to_m2_coord(c))
            if j:
              transitive_jar_path_for_coord.append(j)

        return transitive_jar_path_for_coord

      for jar in t.jar_dependencies:
        # if there are override classifiers, then force use of those.
        coord_candidates = []
        if override_classifiers:
          coord_candidates = [jar.coordinate.copy(classifier=c) for c in override_classifiers]
        else:
          coord_candidates = [jar.coordinate]

        # If there are conflict resolution entries, then update versions to the resolved ones.
        jar_spec = f'{jar.coordinate.org}:{jar.coordinate.name}'
        if jar.coordinate.simple_coord in parsed_output['conflict_resolution']:
          parsed_conflict = CoursierMixin.to_m2_coord(
            parsed_output['conflict_resolution'][jar.coordinate.simple_coord])
          coord_candidates = [c.copy(rev=parsed_conflict.rev) for c in coord_candidates]
        elif jar_spec in org_name_to_org_name_rev:
          parsed_conflict = org_name_to_org_name_rev[jar_spec]
          coord_candidates = [c.copy(rev=parsed_conflict.rev) for c in coord_candidates]

        for coord in coord_candidates:
          transitive_resolved_jars = get_transitive_resolved_jars(coord, coord_to_resolved_jars)
          if transitive_resolved_jars:
            for jar in transitive_resolved_jars:
              jars_to_digest.append(jar)

      jars_per_target.append((t.v1_target, tuple(jars_to_digest)))


  return CoursierResolveResult(
    base_conf=req.conf,
    jars_per_target=tuple(jars_per_target),
  )


@dataclass(frozen=True)
class SnapshottedResolveResult:
  resolution: CoursierResolveResult
  merged_snapshot: Snapshot

  def __getattr__(self, key, **kwargs):
    """Use the prototype pattern with the original coursier resolution resuslt."""
    if hasattr(self.resolution, key):
      return getattr(self.resolution, key)
    return super().__getattr__(key, **kwargs)


@rule
async def snapshotted_coursier_result(
    res: CoursierResolveResult,
    coursier: CoursierSubsystem,
    build_root: BuildRoot,
) -> SnapshottedResolveResult:
  # TODO: figure out whether the arbitrary_root kwarg is the right way to snapshot things outside of
  # the buildroot (which also makes use of the coursier cache)!!
  cache_root = os.path.realpath(coursier.get_options().cache_dir)
  all_jar_paths = [os.path.realpath(j.cache_path) for j in res.resolved_jars]

  jars_in_cache_dir = []
  jars_in_build_root = []
  for p in all_jar_paths:
    if p.startswith(cache_root):
      jars_in_cache_dir.append(fast_relpath(p, cache_root))
    else:
      fast_relpath(p, build_root.path)

  cache_dir_cp, build_root_cp = tuple(await MultiGet([
    Get[Snapshot](PathGlobs(include=jars_in_cache_dir, arbitrary_root=cache_root)),
    Get[Snapshot](PathGlobs(include=jars_in_build_root)),
  ]))
  merged_snapshot = await Get[Snapshot](DirectoriesToMerge(tuple([
    cache_dir_cp.directory_digest,
    build_root_cp.directory_digest,
  ])))
  return SnapshottedResolveResult(resolution=res, merged_snapshot=merged_snapshot)


class TestCoursierResolve(Goal):
  name = 'test-coursier-resolve'


@console_rule
async def test_coursier_resolve(console: Console) -> TestCoursierResolve:
  coursier_result = await Get[SnapshottedResolveResult](CoursierRequest(
    jar_resolution=JarResolveRequest(tuple([
      JarDependency(org='org.pantsbuild', name='zinc-compiler_2.12', rev='0.0.17'),
    ])),
  ))
  console.print_stdout(f'coursier_result: {coursier_result}')
  return TestCoursierResolve(exit_code=0)


def rules():
  return [
    optionable_rule(CoursierSubsystem),
    snapshot_coursier,
    optionable_rule(JarDependencyManagement),
    RootRule(JarResolveRequest),
    generate_coursier_execution_request,
    execute_coursier,
    snapshotted_coursier_result,
    test_coursier_resolve,
  ]
