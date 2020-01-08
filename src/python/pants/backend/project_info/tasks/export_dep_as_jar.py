# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
import zipfile
from collections import defaultdict

from pants.backend.jvm.subsystems.dependency_context import DependencyContext
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.junit_tests import JUnitTests
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.project_info.tasks.export import SourceRootTypes
from pants.backend.project_info.tasks.export_version import DEFAULT_EXPORT_VERSION
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.resources import Resources
from pants.java.distribution.distribution import DistributionLocator
from pants.java.jar.jar_dependency_utils import M2Coordinate
from pants.task.console_task import ConsoleTask
from pants.util.contextutil import temporary_file
from pants.util.memo import memoized_property


class ExportDepAsJar(ConsoleTask):
  """[Experimental] Create project info for IntelliJ with dependencies treated as jars.

  This is an experimental task that mimics export but uses the jars for
  jvm dependencies instead of sources.
  """

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (DependencyContext,)

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--formatted', type=bool, implicit_value=False,
      help='Causes output to be a single line of JSON.')
    register('--sources', type=bool,
      help='Causes the sources of dependencies to be zipped and included in the project.')

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    round_manager.require_data('export_dep_as_jar_classpath')

  @property
  def _output_folder(self):
    return self.options_scope.replace('.', os.sep)

  @staticmethod
  def _source_roots_for_target(target):
    """
    :type target:pants.build_graph.target.Target
    """

    def root_package_prefix(source_file):
      source = os.path.dirname(source_file)
      return os.path.join(get_buildroot(), target.target_base, source), source.replace(os.sep, '.')

    return {root_package_prefix(source) for source in target.sources_relative_to_source_root()}

  @memoized_property
  def target_aliases_map(self):
    registered_aliases = self.context.build_configuration.registered_aliases()
    mapping = {}
    for alias, target_types in registered_aliases.target_types_by_alias.items():
      # If a target class is registered under multiple aliases returns the last one.
      for target_type in target_types:
        mapping[target_type] = alias
    return mapping

  def _get_pants_target_alias(self, pants_target_type):
    """Returns the pants target alias for the given target"""
    if pants_target_type in self.target_aliases_map:
      return self.target_aliases_map.get(pants_target_type)
    else:
      return "{}.{}".format(pants_target_type.__module__, pants_target_type.__name__)

  @staticmethod
  def _jar_id(jar):
    """Create a string identifier for the IvyModuleRef key.
    :param IvyModuleRef jar: key for a resolved jar
    :returns: String representing the key as a maven coordinate
    """
    if jar.rev:
      return '{0}:{1}:{2}'.format(jar.org, jar.name, jar.rev)
    else:
      return '{0}:{1}'.format(jar.org, jar.name)

  @staticmethod
  def _exclude_id(jar):
    """Create a string identifier for the Exclude key.
    :param Exclude jar: key for an excluded jar
    :returns: String representing the key as a maven coordinate
    """
    return '{0}:{1}'.format(jar.org, jar.name) if jar.name else jar.org

  @staticmethod
  def _get_target_type(tgt, resource_target_map):
    def is_test(t):
      return isinstance(t, JUnitTests)

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

  def _resolve_jars_info(self, targets, classpath_products):
    """Consults ivy_jar_products to export the external libraries.

    :return: mapping of jar_id -> { 'default'     : <jar_file>,
                                    'sources'     : <jar_file>,
                                    'javadoc'     : <jar_file>,
                                    <other_confs> : <jar_file>,
                                  }
    """
    mapping = defaultdict(dict)
    jar_products = classpath_products.get_artifact_classpath_entries_for_targets(
      targets, respect_excludes=False)
    for conf, jar_entry in jar_products:
      conf = jar_entry.coordinate.classifier or 'default'
      mapping[self._jar_id(jar_entry.coordinate)][conf] = jar_entry.cache_path
    return mapping

  @staticmethod
  def _zip_sources(target, location, suffix='.jar'):
    with temporary_file(root_dir=location, cleanup=False, suffix=suffix) as f:
      with zipfile.ZipFile(f, 'a') as zip_file:
        for src_from_source_root, src_from_build_root in zip(target.sources_relative_to_source_root(), target.sources_relative_to_buildroot()):
          zip_file.write(os.path.join(get_buildroot(), src_from_build_root), src_from_source_root)
    return f

  def _dependencies_to_include_in_libraries(self, t, modulizable_target_set):
    dependencies_to_include = set([])
    self.context.build_graph.walk_transitive_dependency_graph(
      [direct_dep.address for direct_dep in t.dependencies],
      # NB: Dependency graph between modulizable targets is represented with modules,
      #     so we don't need to expand those branches of the dep graph.
      predicate=lambda dep: dep not in modulizable_target_set,
      work=lambda dep: dependencies_to_include.add(dep),
    )
    return dependencies_to_include

  def _process_target(self, current_target, modulizable_target_set, resource_target_map, runtime_classpath):
    """
    :type current_target:pants.build_graph.target.Target
    """
    info = {
      # this means 'dependencies'
      'targets': [],
      'libraries': [],
      'roots': [],
      'id': current_target.id,
      'target_type': ExportDepAsJar._get_target_type(current_target, resource_target_map),
      'is_synthetic': current_target.is_synthetic,
      'pants_target_type': self._get_pants_target_alias(type(current_target)),
      'is_target_root': current_target in modulizable_target_set,
      'transitive': current_target.transitive,
      'scope': str(current_target.scope)
    }

    if not current_target.is_synthetic:
      info['globs'] = current_target.globs_relative_to_buildroot()

    def iter_transitive_jars(jar_lib):
      """
      :type jar_lib: :class:`pants.backend.jvm.targets.jar_library.JarLibrary`
      :rtype: :class:`collections.Iterator` of
              :class:`pants.java.jar.M2Coordinate`
      """
      if runtime_classpath:
        jar_products = runtime_classpath.get_artifact_classpath_entries_for_targets((jar_lib,))
        for _, jar_entry in jar_products:
          coordinate = jar_entry.coordinate
          # We drop classifier and type_ since those fields are represented in the global
          # libraries dict and here we just want the key into that dict (see `_jar_id`).
          yield M2Coordinate(org=coordinate.org, name=coordinate.name, rev=coordinate.rev)

    def _full_library_set_for_target(target):
      """
      Get the full library set for a target, including jar dependencies and jars of the library itself.
      """
      libraries = set([])
      if isinstance(target, JarLibrary):
        jars = set([])
        for jar in target.jar_dependencies:
          jars.add(M2Coordinate(jar.org, jar.name, jar.rev))
        # Add all the jars pulled in by this jar_library
        jars.update(iter_transitive_jars(target))
        libraries = [self._jar_id(jar) for jar in jars]
      else:
        libraries.add(target.id)
      return libraries

    libraries_for_target = set([self._jar_id(jar) for jar in iter_transitive_jars(current_target)])
    for dep in self._dependencies_to_include_in_libraries(current_target, modulizable_target_set):
      libraries_for_target.update(_full_library_set_for_target(dep))
    info['libraries'].extend(libraries_for_target)

    if current_target in modulizable_target_set:
      info['roots'] = [{
        'source_root': os.path.realpath(source_root_package_prefix[0]),
        'package_prefix': source_root_package_prefix[1]
      } for source_root_package_prefix in self._source_roots_for_target(current_target)]

    for dep in current_target.dependencies:
      if dep in modulizable_target_set:
        info['targets'].append(dep.address.spec)

    if isinstance(current_target, ScalaLibrary):
      for dep in current_target.java_sources:
        info['targets'].append(dep.address.spec)

    if isinstance(current_target, JvmTarget):
      info['excludes'] = [self._exclude_id(exclude) for exclude in current_target.excludes]
      info['platform'] = current_target.platform.name
      if hasattr(current_target, 'test_platform'):
        info['test_platform'] = current_target.test_platform.name

    return info

  def initialize_graph_info(self):
    scala_platform = ScalaPlatform.global_instance()
    scala_platform_map = {
      'scala_version': scala_platform.version,
      'compiler_classpath': [
        cp_entry.path
        for cp_entry in scala_platform.compiler_classpath_entries(self.context.products)
      ],
    }

    jvm_platforms_map = {
      'default_platform': JvmPlatform.global_instance().default_platform.name,
      'platforms': {
        str(platform_name): {
          'target_level': str(platform.target_level),
          'source_level': str(platform.source_level),
          'args': platform.args,
        } for platform_name, platform in JvmPlatform.global_instance().platforms_by_name.items()},
    }

    graph_info = {
      'version': DEFAULT_EXPORT_VERSION,
      'targets': {},
      'jvm_platforms': jvm_platforms_map,
      'scala_platform': scala_platform_map,
      # `jvm_distributions` are static distribution settings from config,
      # `preferred_jvm_distributions` are distributions that pants actually uses for the
      # given platform setting.
      'preferred_jvm_distributions': {}
    }

    for platform_name, platform in JvmPlatform.global_instance().platforms_by_name.items():
      preferred_distributions = {}
      for strict, strict_key in [(True, 'strict'), (False, 'non_strict')]:
        try:
          dist = JvmPlatform.preferred_jvm_distribution([platform], strict=strict)
          preferred_distributions[strict_key] = dist.home
        except DistributionLocator.Error:
          pass

      if preferred_distributions:
        graph_info['preferred_jvm_distributions'][platform_name] = preferred_distributions

    return graph_info

  def _get_all_targets(self, targets):
    additional_java_targets = []
    for t in targets:
      if isinstance(t, ScalaLibrary):
        additional_java_targets.extend(t.java_sources)
    targets.extend(additional_java_targets)
    return set(targets)

  def _get_targets_to_make_into_modules(self, target_roots_set):
    target_root_addresses = [t.address for t in target_roots_set]
    dependees_of_target_roots = self.context.build_graph.transitive_dependees_of_addresses(target_root_addresses)
    return dependees_of_target_roots

  def _make_libraries_entry(self, target, resource_target_map, runtime_classpath):
    # Using resolved path in preparation for VCFS.
    resource_jar_root = os.path.realpath(self.versioned_workdir)
    library_entry = {}
    target_type = ExportDepAsJar._get_target_type(target, resource_target_map)
    if target_type == SourceRootTypes.RESOURCE or target_type == SourceRootTypes.TEST_RESOURCE:
      # yic assumed that the cost to fingerprint the target may not be that lower than
      # just zipping up the resources anyway.
      jarred_resources = ExportDepAsJar._zip_sources(target, resource_jar_root)
      library_entry['default'] = jarred_resources.name
    else:
      jar_products = runtime_classpath.get_for_target(target)
      for conf, jar_entry in jar_products:
        # TODO(yic): check --compile-rsc-use-classpath-jars is enabled.
        # If not, zip up the classes/ dir here.
        if 'z.jar' in jar_entry:
          library_entry[conf] = jar_entry
      if self.get_options().sources:
        # NB: We create the jar in the same place as we create the resources
        # (as opposed to where we store the z.jar), because the path to the z.jar depends
        # on tasks outside of this one.
        # In addition to that, we may not want to depend on z.jar existing to export source jars.
        jarred_sources = ExportDepAsJar._zip_sources(target, resource_jar_root, suffix='-sources.jar')
        library_entry['sources'] = jarred_sources.name
    return library_entry

  def generate_targets_map(self, targets, runtime_classpath):
    """Generates a dictionary containing all pertinent information about the target graph.

    The return dictionary is suitable for serialization by json.dumps.
    :param all_targets: The list of targets to generate the map for.
    :param classpath_products: Optional classpath_products. If not provided when the --libraries
      option is `True`, this task will perform its own jar resolution.
    """
    target_roots_set = set(self.context.target_roots)

    all_targets = self._get_all_targets(targets)
    libraries_map = self._resolve_jars_info(all_targets, runtime_classpath)

    targets_map = {}
    resource_target_map = {}

    for t in all_targets:
      for dep in t.dependencies:
        if isinstance(dep, Resources):
          resource_target_map[dep] = t

    modulizable_targets = self._get_targets_to_make_into_modules(target_roots_set)
    non_modulizable_targets = all_targets.difference(modulizable_targets)

    for t in non_modulizable_targets:
      libraries_map[t.id] = self._make_libraries_entry(t, resource_target_map, runtime_classpath)

    for target in modulizable_targets:
      info = self._process_target(target, modulizable_targets, resource_target_map, runtime_classpath)
      targets_map[target.address.spec] = info

    graph_info = self.initialize_graph_info()
    graph_info['targets'] = targets_map
    graph_info['libraries'] = libraries_map

    return graph_info

  def console_output(self, targets):
    runtime_classpath = self.context.products.get_data('export_dep_as_jar_classpath')
    if runtime_classpath is None:
      raise TaskError("There was an error compiling the targets - There is no export_dep_as_jar classpath")
    graph_info = self.generate_targets_map(targets, runtime_classpath=runtime_classpath)
    if self.get_options().formatted:
      return json.dumps(graph_info, indent=4, separators=(',', ': ')).splitlines()
    else:
      return [json.dumps(graph_info)]
