# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import FrozenSet, Tuple

from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.backend.jvm.rules.hermetic_dist import HermeticDist
from pants.engine.fs import Digest, DirectoriesToMerge, Snapshot
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.objects import Collection
from pants.engine.rules import optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.util.memo import memoized_classproperty


@dataclass(frozen=True)
class ThriftableTarget:
  underlying: HydratedTarget

  @memoized_classproperty
  def known_build_file_aliases(cls) -> FrozenSet[str]:
    # FIXME: copied from register.py!
    return frozenset([
      'java_antlr_library',
      'java_protobuf_library',
      'java_ragel_library',
      'java_thrift_library',
      'java_wire_library',
      'python_antlr_library',
      'python_thrift_library',
      'python_grpcio_library',
      'jaxb_library',
    ])



ThriftableTargets = Collection[ThriftableTarget]


@rule
def collect_thriftable_targets(thts: TransitiveHydratedTargets) -> ThriftableTargets:
  return ThriftableTargets(
    ThriftableTarget(hydrated_target)
    for hydrated_target in thts.closure
    if hydrated_target.adaptor.type_alias in ThriftableTarget.known_build_file_aliases
  )


@dataclass(frozen=True)
class ThriftGenRequest:
  exe_req: ExecuteProcessRequest


@rule
def create_thrift_gen_request(
    thriftable_target: ThriftableTarget,
    thrift_defaults: ThriftDefaults,
    hermetic_dist: HermeticDist,
) -> ThriftGenRequest:

  hydrated_target = thriftable_target.underlying
  target = hydrated_target.adaptor

  args = list(thrift_defaults.compiler_args(target))

  default_java_namespace = thrift_defaults.default_java_namespace(target)
  if default_java_namespace:
    args.extend(['--default-java-namespace', default_java_namespace])

  # NB: No need to set import paths here, because we can materialize all the target's dependencies
  # relative to their source root!

  # TODO: validate language!
  output_language = thrift_defaults.language(target)
  args.extend(['--language', output_language])

  namespace_map = thrift_defaults.namespace_map(target)
  namespace_map = tuple(sorted(namespace_map.items())) if namespace_map else ()
  for lhs, rhs in namespace_map:
    args.extend(['--namespace-map', f'{lhs}={rhs}'])

  # TODO: do we need to account for `target.include_paths`?

  args.append('--verbose')

  # TODO: do we need to support --gen-file-map?

  # TODO: add dependencies!!!!!!!!!

  cur_target_source_root_stripped_sources = await Get[SourceRootStrippedSources](HydratedTarget,
                                                                                 hydrated_target)
  dependency_source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, dep)
    for dep in hydrated_target.dependencies
  )

  merged_input_files = await Get[Digest](DirectoriesToMerge(tuple(
    [cur_target_source_root_stripped_sources.snapshot.directory_digest] + [
      dep_sources.snapshot.directory_digest
      for dep_sources in dependency_source_root_stripped_sources
    ])))

  expected_output_files = [
    re.replace(r'\.thrift$', f'.{output_language}', file_name)
    for file_name in cur_target_source_root_stripped_sources.snapshot.files
  ]

  exe_req = ExecuteProcessRequest(
    argv=tuple([
      '.jdk/bin/java',
      '-cp', ':'.join([
        # TODO: get classspath for scrooge!!!!!!!
      ])
    ]),
    input_files=merged_input_files,
    description=f'Invoke scrooge for the sources of the target {hydrated_target.address}',
    output_files=tuple(expected_output_files),
    jdk_home=hermetic_dist.underlying_home,
    is_nailgunnable=True,
  )
  return ThriftGenRequest(exe_req)


@dataclass(frozen=True)
class ThriftedTarget:
  original: HydratedTarget
  output: Snapshot


@dataclass(frozen=True)
class ThriftResults:
  thrifted_targets: Tuple[ThriftedTarget, ...]


@rule
def fast_thrift_gen():
  return None


def rules():
  return [
    collect_thriftable_targets,
    optionable_rule(ThriftDefaults),
    create_thrift_gen_request,
    fast_thrift_gen,
  ]
