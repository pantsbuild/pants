# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from abc import ABC, abstractproperty
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Set, Tuple, Type, cast

from pex.interpreter import PythonInterpreter
from twitter.common.collections import OrderedSet

from pants.backend.codegen.thrift.java.rules.thrift_gen import ThriftedTarget
from pants.backend.jvm.rules.coursier import (CoursierRequest, JarResolveRequest,
                                              ResolveConfiguration, SnapshottedResolveResult)
from pants.backend.jvm.rules.jvm_options import JvmOptions
from pants.backend.jvm.rules.jvm_tool import JvmToolClasspathResult
from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolRequest
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.project_info.tasks.export import (ExportTask, SourceRootTypes,
                                                     DEFAULT_EXPORT_VERSION)
from pants.backend.python.interpreter_cache import PythonInterpreterCache
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.rules.pex import (CreatePex, Pex, PexInterpreterConstraints,
                                            PexRequirements)
from pants.backend.python.subsystems.pex_build_util import has_python_requirements
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_root import BuildRoot
from pants.base.hash_utils import stable_json_sha1
from pants.base.specs import Specs
from pants.build_graph.address import Address
from pants.build_graph.build_configuration import BuildConfiguration
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.engine.addressable import BuildFileAddress, BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.objects import Collection
from pants.engine.rules import console_rule, optionable_rule, rule
from pants.engine.selectors import Get, MultiGet
from pants.help.build_dictionary_info_extracter import BuildDictionaryInfoExtracter
from pants.java.distribution.distribution import Distribution, DistributionLocator
from pants.java.jar.jar_dependency import JarDependency
from pants.java.jar.jar_dependency_utils import M2Coordinate, ResolvedJar
from pants.option.custom_types import dir_option
from pants.source.source_root import SourceRoot, SourceRootConfig
from pants.util.collections import Enum
from pants.util.dirutil import fast_relpath, fast_relpath_collection
from pants.util.memo import memoized_property


class ExportTarget(ABC):

  @abstractproperty
  def hydrated_target(self) -> HydratedTarget: ...

  @abstractproperty
  def is_synthetic(self) -> bool: ...


@dataclass(frozen=True)
class SourceTarget(ExportTarget):
  _hydrated_target: HydratedTarget

  @property
  def hydrated_target(self):
    return self._hydrated_target

  is_synthetic = False


@dataclass(frozen=True)
class SyntheticTarget(ExportTarget):
  thrifted_target: ThriftedTarget

  @property
  def hydrated_target(self):
    return self.thrifted_target.original

  is_synthetic = True


@dataclass(frozen=True)
class TargetAliasesMap:
  aliases: Tuple[Tuple[Type[Target], str], ...]
  all_symbols: Tuple[str, ...]

  @memoized_property
  def aliases_mapping(self) -> Dict[Type[Target], str]:
    # If a target class is registered under multiple aliases, we return the last one.
    return {
      ty: alias
      for ty, alias in self.aliases
    }


@rule
def make_target_aliases_map(build_config: BuildConfiguration) -> TargetAliasesMap:
  registered_aliases = build_config.registered_aliases()

  aliases = [
    (ty, alias)
    for alias, target_types in registered_aliases.target_types_by_alias.items()
    for ty in target_types
  ]

  extracter = BuildDictionaryInfoExtracter(registered_aliases)

  return TargetAliasesMap(
    aliases=tuple(aliases),
    all_symbols=tuple(x.symbol for x in extracter.get_target_type_info()))


@dataclass(frozen=True)
class SourceRootedSourceFile:
  path: Path
  package_prefix: str


class SourceRootedSourcesForTarget(Collection[SourceRootedSourceFile]): pass


@rule
def source_root_for_target(
    source_root_config: SourceRootConfig,
    hydrated_target: HydratedTarget,
) -> SourceRoot:
  all_source_roots = source_root_config.get_source_roots()
  return all_source_roots.find_by_path(hydrated_target.address.spec_path)


@rule
def rooted_sources_for_target(
    source_root_config: SourceRootConfig,
    hydrated_target: HydratedTarget,
    build_root: BuildRoot,
    source_root: SourceRoot,
) -> SourceRootedSourcesForTarget:
  sources = getattr(hydrated_target.adaptor, 'sources', None)
  if not sources:
    return SourceRootedSourcesForTarget(())

  relative_source_paths = zip(
    sources.files_relative_to_buildroot,
    fast_relpath_collection(sources.files_relative_to_buildroot, root=source_root.path))
  return SourceRootedSourcesForTarget(tuple(
    SourceRootedSourceFile(
      path=build_root.new_path.resolve(build_root_rel_path),
      package_prefix=source_root_rel_path.replace(os.sep, '.'),
    )
    for build_root_rel_path, source_root_rel_path in relative_source_paths
  ))


@dataclass(frozen=True)
class PythonTargetSet:
  interpreter: PythonInterpreter
  targets: Tuple[Target, ...]


@dataclass(frozen=True)
class JustRequirementsPex:
  interpreter: PythonInterpreter
  pex: Pex


@rule
async def find_pex_for_target_set(target_set: PythonTargetSet) -> JustRequirementsPex:
  interpreter = target_set.interpreter
  bfas = [
    BuildFileAddress(
      target_name=t.address.target_name,
      # TODO: this is a hack so that the BuildFileAddress's spec_path will be set to the dirname of
      # this path!
      rel_path=os.path.join(t.address.spec_path, 'BUILD'))
    for t in target_set.targets
  ]
  thts = await Get[TransitiveHydratedTargets](BuildFileAddresses(tuple(bfas)))
  req_libs = [target.adaptor
              for target in thts.closure
              if has_python_requirements(target.adaptor.v1_target)]
  pex_filename_base = stable_json_sha1(tuple(
    adaptor._key()
    for adaptor in req_libs
  ))

  pex = await Get[Pex](CreatePex(
    output_filename=f'{pex_filename_base}.pex',
    requirements=PexRequirements.create_from_adaptors(req_libs),
    interpreter_constraints=PexInterpreterConstraints.create_from_interpreter(interpreter),
  ))

  return JustRequirementsPex(interpreter, pex)

  interpreters_info[str(interpreter.identity)] = {
    'binary': interpreter.binary,
    'pex': pex
  }



class Export(Goal):
  """Generates a dictionary containing all pertinent information about the target graph.

  The return dictionary is suitable for serialization by json.dumps.
  """
  name = 'export-v2'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--libraries', default=True, type=bool,
             help='Causes libraries to be output.')
    register('--libraries-sources', type=bool,
             help='Causes libraries with sources to be output.')
    register('--libraries-javadocs', type=bool,
             help='Causes libraries with javadocs to be output.')
    register('--available-target-types', type=bool,
             default=False,
             help='Causes a list of available target types to be output.')
    register('--sources', type=bool,
             help='Causes sources to be output.')
    register('--formatted', type=bool, implicit_value=False,
             help='Causes output to be a single line of JSON.')
    register('--jvm-options', type=list, metavar='<option>...',
             help='Run the JVM 3rdparty resolver with these jvm options.')
    register('--output-file', metavar='<path>',
             help='Write the console output to this file instead.')
    register('--output-dir', type=dir_option, default='.',
             help='Directory to export generated sources and 3rdparty jars to.')


def _get_pants_target_alias(target_aliases_map: TargetAliasesMap, pants_target_type: Type[Target]):
  """"Return the pants target alias for the given target."""
  target_alias = (target_aliases_map.aliases_mapping.get(pants_target_type, None) or
                  f"{pants_target_type.__module__}.{pants_target_type.__name__}")
  return target_alias


@dataclass(frozen=True)
class ResolvedJarsInfo:
  resolved_jars: Tuple[Tuple[ResolvedJar, ResolveConfiguration], ...]

  @memoized_property
  def json_mapping(self) -> Dict[str, Dict[str, str]]:
    ret = defaultdict(dict)
    for jar_entry, conf in self.resolved_jars:
      ret[ExportTask.jar_id(jar_entry.coordinate)][conf] = jar_entry.cache_path
    return cast(Dict[str, Dict[str, str]], ret)


@rule
def extract_resolved_jars_info(res: SnapshottedResolveResult) -> ResolvedJarsInfo:
  ret: List[Tuple(ResolvedJar, ResolveConfiguration)] = []
  for jar_entry in res.resolved_jars:
    conf = cast(ResolveConfiguration, jar_entry.coordinate.classifier or res.base_conf.conf)
    ret.append((jar_entry, conf))
  return ResolvedJarsInfo(tuple(ret))


@console_rule
async def export_v2(
    console: Console,
    build_root: BuildRoot,
    workspace: Workspace,
    target_aliases_map: TargetAliasesMap,
    specs: Specs,
    interpreter_cache: PythonInterpreterCache,
    jvm_platform: JvmPlatform,
    scala_platform: ScalaPlatform,
    export_options: Export.Options,
) -> Export:
  export_options = export_options.values

  thts = await Get[TransitiveHydratedTargets](Specs, specs)

  targets_map = {}
  resource_target_map = {}
  python_interpreter_targets_mapping = defaultdict(list)

  if export_options.libraries:
    # TODO: support excludes!
    resolve_result = await Get[SnapshottedResolveResult](CoursierRequest(
      jar_resolution=JarResolveRequest(thts),
      jvm_options=JvmOptions(tuple(export_options.jvm_options)),
      jar_path_base=Path(export_options.output_dir),
    ))
  else:
    resolve_result = None

  target_roots_set = frozenset(t.adaptor for t in thts.roots)

  async def process_target(export_target: ExportTarget):
    """
    :type current_target:pants.build_graph.target.Target
    """
    hydrated_target = export_target.hydrated_target
    current_target = hydrated_target.adaptor

    def get_target_type(tgt):
      def is_test(t):
        return isinstance(t, (JUnitTests, PythonTests))
      if is_test(tgt):
        return SourceRootTypes.TEST
      else:
        if (isinstance(tgt, Resources) and
            tgt in resource_target_map and
              is_test(resource_target_map[tgt])):
          return SourceRootTypes.TEST_RESOURCE
        elif isinstance(tgt, Resources):
          return SourceRootTypes.RESOURCE
        else:
          return SourceRootTypes.SOURCE

    info = {
      'targets': [],
      'libraries': [],
      'roots': [],
      'id': current_target.v1_target.id,
      'target_type': get_target_type(current_target.v1_target),
      'is_synthetic': export_target.is_synthetic,
      'pants_target_type': _get_pants_target_alias(target_aliases_map,
                                                   type(current_target.v1_target)),
    }

    if (not export_target.is_synthetic) and hasattr(current_target, 'sources'):
      info['globs'] = current_target.sources.filespec['globs']
      if export_options.sources:
        info['sources'] = list(current_target.sources.files_relative_to_buildroot)

    info['transitive'] = current_target.v1_target.transitive
    info['scope'] = str(current_target.v1_target.scope)
    info['is_target_root'] = current_target in target_roots_set

    if isinstance(current_target.v1_target, PythonRequirementLibrary):
      reqs = cast(Set[PythonRequirement], current_target.v1_target.payload.get_field_value('requirements', set()))
      info['requirements'] = [req.key for req in reqs]

    if isinstance(current_target.v1_target, PythonTarget):
      interpreter_for_target = interpreter_cache.select_interpreter_for_targets(
        [current_target.v1_target])
      if interpreter_for_target is None:
        console.print_stderr(f'Unable to find suitable interpreter for {current_target.address}')
        return Export(exit_code=1)
      python_interpreter_targets_mapping[interpreter_for_target].append(current_target)
      info['python_interpreter'] = str(interpreter_for_target.identity)

    def iter_transitive_jars(jar_lib):
      """
      :type jar_lib: :class:`pants.backend.jvm.targets.jar_library.JarLibrary`
      :rtype: :class:`collections.Iterator` of
              :class:`pants.java.jar.M2Coordinate`
      """
      if resolve_result:
        jar_products = resolve_result.resolution.target_jars_mapping[jar_lib]
        for jar_entry in jar_products:
          coordinate = jar_entry.coordinate
          # We drop classifier and type_ since those fields are represented in the global
          # libraries dict and here we just want the key into that dict (see `jar_id`).
          yield M2Coordinate(org=coordinate.org, name=coordinate.name, rev=coordinate.rev)

    target_libraries = OrderedSet()
    if isinstance(current_target, JarLibrary):
      target_libraries = OrderedSet(iter_transitive_jars(current_target.v1_target))
    cur_deps = await MultiGet(Get[HydratedTarget](Address, a) for a in current_target.dependencies)
    for dep in cur_deps:
      dep = dep.adaptor.v1_target
      info['targets'].append(dep.address.spec)
      if isinstance(dep, JarLibrary):
        for jar in dep.jar_dependencies:
          target_libraries.add(M2Coordinate(jar.org, jar.name, jar.rev))
        # Add all the jars pulled in by this jar_library
        target_libraries.update(iter_transitive_jars(dep))
      if isinstance(dep, Resources):
        resource_target_map[dep] = current_target

    java_sources = getattr(current_target, 'java_sources', [])
    for dep in java_sources:
      info['targets'].append(dep.address.spec)
      await process_target(SourceTarget(dep))

    if isinstance(current_target.v1_target, JvmTarget):
      info['excludes'] = [
        ExportTask._exclude_id(exclude) for exclude in current_target.v1_target.excludes
      ]
      payload = current_target.v1_target.payload
      info['platform'] = jvm_platform.get_platform_by_name(
        name=payload.platform,
        for_target=current_target,
      ).name
      if hasattr(payload, 'test_platform'):
        info['test_platform'] = jvm_platform.get_platform_by_name(
          name=payload.test_platform,
          for_target=current_target,
        ).name

    rooted_sources_for_target = await Get[SourceRootedSourcesForTarget](
      HydratedTarget, hydrated_target)
    info['roots'] = [{
      'source_root': str(rooted_source_file.path),
      'package_prefix': rooted_source_file.package_prefix,
    } for rooted_source_file in rooted_sources_for_target]

    if target_libraries:
      info['libraries'] = [ExportTask.jar_id(lib) for lib in target_libraries]
    targets_map[current_target.address.spec] = info

  for ht in thts.closure:
    await process_target(SourceTarget(ht))


  scala_compiler_classpath = await Get[JvmToolClasspathResult](
    JvmToolRequest, scala_platform.create_tool_request('scalac'))
  scala_platform_map = {
    'scala_version': scala_platform.version,
    'compiler_classpath': [
      os.path.join(build_root.path, rel_path)
      for rel_path in
      (scala_compiler_classpath.snapshot.files + scala_compiler_classpath.snapshot.dirs)
    ],
  }

  jvm_platforms_map = {
    'default_platform' : jvm_platform.default_platform.name,
    'platforms': {
      str(platform_name): {
        'target_level' : str(platform.target_level),
        'source_level' : str(platform.source_level),
        'args' : platform.args,
      } for platform_name, platform in jvm_platform.platforms_by_name.items()
    },
  }

  graph_info = {
    'version': DEFAULT_EXPORT_VERSION,
    'targets': targets_map,
    'jvm_platforms': jvm_platforms_map,
    'scala_platform': scala_platform_map,
    # `jvm_distributions` are static distribution settings from config,
    # `preferred_jvm_distributions` are distributions that pants actually uses for the
    # given platform setting.
    'preferred_jvm_distributions': {}
  }

  for platform_name, platform in jvm_platform.platforms_by_name.items():
    preferred_distributions = {}
    for strict, strict_key in [(True, 'strict'), (False, 'non_strict')]:
      try:
        dist = JvmPlatform.preferred_jvm_distribution([platform], strict=strict)
        preferred_distributions[strict_key] = dist.home
      except DistributionLocator.Error:
        pass

    if preferred_distributions:
      graph_info['preferred_jvm_distributions'][platform_name] = preferred_distributions

  if resolve_result:
    resolved_jars_info = await Get[ResolvedJarsInfo](SnapshottedResolveResult, resolve_result)
    graph_info['libraries'] = resolved_jars_info.json_mapping

  if python_interpreter_targets_mapping:
    # NB: We've selected a python interpreter compatible with each python target individually into
    # the `python_interpreter_targets_mapping`. These python targets may not be compatible, ie: we
    # could have a python target requiring 'CPython>=2.7<3' (ie: CPython-2.7.x) and another
    # requiring 'CPython>=3.6'. To pick a default interpreter then from among these two choices
    # is arbitrary and not to be relied on to work as a default interpreter if ever needed by the
    # export consumer.
    #
    # TODO(John Sirois): consider either eliminating the 'default_interpreter' field and pressing
    # export consumers to make their own choice of a default (if needed) or else use
    # `select.select_interpreter_for_targets` and fail fast if there is no interpreter compatible
    # across all the python targets in-play.
    #
    # For now, make our arbitrary historical choice of a default interpreter explicit and use the
    # lowest version.
    default_interpreter = min(python_interpreter_targets_mapping.keys())

    requirement_pexes = await MultiGet(
      Get[JustRequirementsPex](PythonTargetSet(interpreter, tuple(targets)))
      for interpreter, targets in python_interpreter_targets_mapping.items())

    merged_req_pex_digests = await Get[Digest](DirectoriesToMerge(tuple(
      req_pex.pex.directory_digest
      for req_pex in requirement_pexes
    )))

    output_files = workspace.materialize_directory(DirectoryToMaterialize(
      merged_req_pex_digests,
      path_prefix=(fast_relpath(export_options.output_dir, build_root.path)
                   if os.path.isabs(export_options.output_dir)
                   else export_options.output_dir)))

    interpreters_info = {
      str(pex.interpreter.identity): {
        'binary': pex.interpreter.binary,
        'pex': pex.pex.output_filename,
        'chroot': pex.pex.output_filename,
      }
      for pex in requirement_pexes
    }

    graph_info['python_setup'] = {
      'default_interpreter': str(default_interpreter.identity),
      'interpreters': interpreters_info,
    }

  if export_options.available_target_types:
    graph_info['available_target_types'] = target_aliases_map.all_symbols


  export_json = json.dumps(graph_info)
  if export_options.output_file:
    with open(export_options.output_file, 'w') as f:
      f.write(export_json)
  else:
    console.print_stdout(export_json)
  console.print_stdout('\n')

  return Export(exit_code=0)


def rules():
  return [
    make_target_aliases_map,
    source_root_for_target,
    rooted_sources_for_target,
    extract_resolved_jars_info,
    find_pex_for_target_set,
    optionable_rule(PythonInterpreterCache),
    optionable_rule(JvmPlatform),
    optionable_rule(ScalaPlatform),
    export_v2,
  ]
