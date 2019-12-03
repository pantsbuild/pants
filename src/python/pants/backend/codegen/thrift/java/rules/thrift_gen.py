# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import re
from dataclasses import dataclass
from typing import FrozenSet, Tuple

from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.backend.jvm.rules.hermetic_dist import HermeticDist
from pants.backend.jvm.rules.jvm_tool import JvmToolClasspathResult
from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin, JvmToolRequest
from pants.build_graph.address import Address
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, Snapshot
from pants.engine.goal import Goal
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.objects import Collection
from pants.engine.rules import RootRule, console_rule, optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.strip_source_root import SourceRootStrippedSources
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_classproperty


class ThriftGenTool(Subsystem, JvmToolMixin):
  options_scope = 'v2-thrift-gen-tool'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    cls.register_jvm_tool(register, 'v2-thrift-gen')


class TestThriftGenClasspath(Goal):
  name = 'test-thrift-gen-classpath'


@console_rule
async def test_thrift_gen_tool_classpath(
    console: Console,
    thrift_gen_tool: ThriftGenTool,
) -> TestThriftGenClasspath:
  classpath_result = await Get[JvmToolClasspathResult](JvmToolRequest,
                                                       thrift_gen_tool.create_tool_request('v2-thrift-gen'))
  console.print_stdout(f'classpath_result: {classpath_result}')
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
    thrift_gen_tool: ThriftGenTool,
) -> ThriftGenRequest:

  # Extract the underlying HydratedTarget, then the v2 TargetAdaptor, then the v1 Target.
  hydrated_target = thriftable_target.underlying
  v2_target = hydrated_target.adaptor
  v1_target = v2_target.v1_target

  args = list(thrift_defaults.compiler_args(v1_target))

  default_java_namespace = thrift_defaults.default_java_namespace(v1_target)
  if default_java_namespace:
    args.extend(['--default-java-namespace', default_java_namespace])

  # NB: No need to set import paths here, because we can materialize all the target's dependencies
  # relative to their source root!

  output_language = thrift_defaults.language(v1_target)
  args.extend(['--language', output_language])

  namespace_map = thrift_defaults.namespace_map(v1_target)
  namespace_map = tuple(sorted(namespace_map.items())) if namespace_map else ()
  for lhs, rhs in namespace_map:
    args.extend(['--namespace-map', f'{lhs}={rhs}'])

  # TODO: do we need to account for `v1_target.include_paths`?

  args.append('--verbose')

  # TODO: do we need to support --gen-file-map?

  cur_target_source_root_stripped_sources = await Get[SourceRootStrippedSources](HydratedTarget,
                                                                                 hydrated_target)
  dependency_source_root_stripped_sources = await MultiGet(
    Get[SourceRootStrippedSources](HydratedTarget, dep)
    for dep in hydrated_target.dependencies
  )

  thrift_gen_classpath_result = await Get[JvmToolClasspathResult](
    JvmToolRequest, thrift_gen_tool.create_tool_request('v2-thrift-gen'))

  merged_input_files = await Get[Digest](DirectoriesToMerge(tuple(
    [
      thrift_gen_classpath_result.snapshot.directory_digest,
      cur_target_source_root_stripped_sources.snapshot.directory_digest
    ] + [
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
      '-cp', ':'.join(thrift_gen_classpath_result.snapshot.files),
    ]),
    input_files=merged_input_files,
    description=f'Invoke scrooge for the sources of the target {hydrated_target.address}',
    output_files=tuple(expected_output_files),
    jdk_home=hermetic_dist.underlying_home,
    is_nailgunnable=True,
  )
  return ThriftGenRequest(exe_req)


class TestThriftGenRequestCreation(Goal):
  name = 'test-thrift-gen-request-creation'


@console_rule
async def test_thrift_gen_request_creation(
    console: Console,
) -> TestThriftGenRequestCreation:
  example_target_spec = Address.parse('testprojects/src/thrift/org/pantsbuild/testproject:thrift-java')
  target = await Get[HydratedTarget](Address, example_target_spec)
  req = await Get[ThriftGenRequest](ThriftableTarget(target))
  console.print_stdout(f'req: {req}')
  return TestThriftGenRequestCreation(exit_code=0)


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
    test_thrift_gen_tool_classpath,
    collect_thriftable_targets,
    optionable_rule(ThriftDefaults),
    RootRule(ThriftableTarget),
    create_thrift_gen_request,
    test_thrift_gen_request_creation,
    fast_thrift_gen,
  ]
