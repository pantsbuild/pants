# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.jvm.rules.coursier import JarResolveRequest, SnapshottedResolveResult
from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolRequest
from pants.build_graph.address import Address
from pants.engine.fs import Snapshot
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import UnionRule, rule, union
from pants.engine.selectors import Get
from pants.util.collections import Enum


class JvmToolBootstrapError(Exception): pass


class JvmToolBootstrapTargetTypes(Enum):
  jar_library = 'jar_library'


@union
class ClasspathRequest: pass


@dataclass(frozen=True)
class JarLibraryClasspathRequest:
  jar_req: JarResolveRequest


@dataclass(frozen=True)
class JvmToolClasspathResult:
  snapshot: Snapshot


@rule
async def snapshot_jar_library_classpath(req: JarLibraryClasspathRequest) -> JvmToolClasspathResult:
  result = await Get[SnapshottedResolveResult](JarResolveRequest, req.jar_req)
  return JvmToolClasspathResult(result.merged_snapshot)


@rule
async def obtain_jvm_tool_classpath(jvm_tool_request: JvmToolRequest) -> JvmToolClasspathResult:
  hydrated_target_from_jvm_tool = await Get[HydratedTarget](Address, jvm_tool_request.address)
  target_adaptor = hydrated_target_from_jvm_tool.adaptor

  # Do an enum "pattern match" to obtain the appropriate strategy for resolving a classpath from the
  # target!
  try:
    jvm_tool_classpath_req = JvmToolBootstrapTargetTypes(target_adaptor.type_alias).match({
      JvmToolBootstrapTargetTypes.jar_library: lambda: JarLibraryClasspathRequest(
        JarResolveRequest(tuple(target_adaptor.jars)))
    })()
  except ValueError as e:
    raise JvmToolBootstrapError(f'unrecognized target type: {e} for'
                                f'jvm tool request: {jvm_tool_request}! '
                                f'recognized target types are: {list(JvmToolBootstrapTargetTypes)}!')

  # Yield back to the engine using the ClasspathRequest @union to select the appropriate strategy!
  return await Get[JvmToolClasspathResult](ClasspathRequest, jvm_tool_classpath_req)


def rules():
  return [
    UnionRule(ClasspathRequest, JarLibraryClasspathRequest),
    snapshot_jar_library_classpath,
    obtain_jvm_tool_classpath,
  ]
