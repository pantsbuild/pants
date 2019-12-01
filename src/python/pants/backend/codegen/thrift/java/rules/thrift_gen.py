# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import FrozenSet, Tuple

from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.backend.jvm.rules.coursier import JarResolveRequest, SnapshottedResolveResult
from pants.backend.jvm.rules.hermetic_dist import HermeticDist
from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.build_graph.address import Address
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, Snapshot
from pants.engine.goal import Goal
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.objects import Collection
from pants.engine.rules import RootRule, UnionRule, console_rule, optionable_rule, rule, union
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.subsystem.subsystem import Subsystem
from pants.util.collections import Enum
from pants.util.memo import memoized_classproperty


class ThriftGenTool(Subsystem, JvmToolMixin):
  options_scope = 'v2-thrift-gen-tool'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    cls.register_jvm_tool(register, 'v2-thrift-gen')


# TODO: make a way to depend on the //:v2-thrift-gen target, even if that target is a jvm_binary()
# (as well as a jar_library())!!!!
@dataclass(frozen=True)
class ThriftGenToolRequest:
  address: Address


# TODO: request a ThriftGenTool from some downstream rule and construct this!! Otherwise the
# `test_thrift_gen_tool_classpath` rule fails with:
# Exception message: Rules with errors: 1
#   (TestThriftGenClasspath, [Console], [Get(ThriftGenToolClasspath, ThriftGenToolRequest)], test_thrift_gen_tool_classpath()):
#     Was not usable by any other @rule.
# @rule
# def create_thrift_gen_tool_request(thrift_gen_tool: ThriftGenTool) -> ThriftGenToolRequest:
#   v2_thrift_gen_pointed_to_target = thrift_gen_tool.get_options().v2_thrift_gen
#   thrift_gen_source_address = Address.parse(v2_thrift_gen_pointed_to_target)
#   return thrift_gen_source_address
@dataclass(frozen=True)
class ThriftGenToolClasspath:
  snapshot: Snapshot


# TODO: put this somewhere more generic!
class JvmToolBootstrapError(Exception): pass


# TODO: put this somewhere more generic!
class JvmToolBootstrapTargetTypes(Enum):
  jar_library = 'jar_library'


# TODO: put this somewhere more generic!
@union
class ClasspathRequest: pass


@dataclass(frozen=True)
class JarLibraryClasspathRequest:
  jar_req: JarResolveRequest


@rule
async def snapshot_jar_library_classpath(req: JarLibraryClasspathRequest) -> ThriftGenToolClasspath:
  result = await Get[SnapshottedResolveResult](JarResolveRequest, req.jar_req)
  return ThriftGenToolClasspath(result.merged_snapshot)


@rule
async def obtain_thrift_gen_tool_classpath(thrift_gen_tool_request: ThriftGenToolRequest) -> ThriftGenToolClasspath:
  hydrated_target_for_thrift_gen = await Get[HydratedTarget](Address, thrift_gen_tool_request.address)
  target_adaptor = hydrated_target_for_thrift_gen.adaptor

  try:
    thrift_gen_classpath_req = JvmToolBootstrapTargetTypes(target_adaptor.type_alias).match({
      JvmToolBootstrapTargetTypes.jar_library: lambda: JarLibraryClasspathRequest(
        JarResolveRequest(tuple(target_adaptor.jars)))
    })()
  except ValueError as e:
    raise JvmToolBootstrapError(f'unrecognized target type: {e} for'
                                f'thrift gen tool request: {thrift_gen_tool_request}! '
                                f'recognized target types are: {list(JvmToolBootstrapTargetTypes)}!')

  return await Get[ThriftGenToolClasspath](ClasspathRequest, thrift_gen_classpath_req)


class TestThriftGenClasspath(Goal):
  name = 'test-thrift-gen-classpath'


@console_rule
async def test_thrift_gen_tool_classpath(console: Console) -> TestThriftGenClasspath:
  target_result = await Get[ThriftGenToolClasspath](ThriftGenToolRequest(Address.parse('//:v2-thrift-gen')))
  console.print_stdout(f'target_result: {target_result}')
  return TestThriftGenClasspath(exit_code=0)


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


class ThriftableTargets(Collection[ThriftableTarget]): pass


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
async def create_thrift_gen_request(
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

  # NB: To calculate the output files to capture, we replace the .thrift file extension with
  # .<language>, where <language> is the value computed for the --language argument above!
  expected_output_files = [
    re.sub(r'\.thrift$', f'.{output_language}', file_name)
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
def fast_thrift_gen() -> ThriftResults:
  return None


def rules():
  return [
    optionable_rule(ThriftGenTool),
    # create_thrift_gen_tool_request,
    # RootRule(ThriftGenToolRequest),
    RootRule(JarLibraryClasspathRequest),
    UnionRule(ClasspathRequest, JarLibraryClasspathRequest),
    snapshot_jar_library_classpath,
    obtain_thrift_gen_tool_classpath,
    test_thrift_gen_tool_classpath,
    collect_thriftable_targets,
    optionable_rule(ThriftDefaults),
    RootRule(ThriftableTarget),
    create_thrift_gen_request,
    fast_thrift_gen,
  ]
