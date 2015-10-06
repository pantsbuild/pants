# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from collections import defaultdict

import six
from pex.pex_info import PexInfo
from twitter.common.collections import OrderedSet

from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.ivy_utils import IvyModuleRef
from pants.backend.jvm.jar_dependency_utils import M2Coordinate
from pants.backend.jvm.subsystems.jvm_platform import JvmPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_target import PythonTarget
from pants.backend.python.tasks.python_task import PythonTask
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.java.distribution.distribution import DistributionLocator
from pants.util.memo import memoized_property


# Changing the behavior of this task may affect the IntelliJ Pants plugin.
# Please add fkorotkov, tdesai to reviews for this file.
class Export(PythonTask, ConsoleTask):
  """Generates a JSON description of the targets as configured in pants.

  Intended for exporting project information for IDE, such as the IntelliJ Pants plugin.
  """

  # FORMAT_VERSION_NUMBER: Version number for identifying the export file format output. This
  # version number should change when there is a change to the output format.
  #
  # Major Version 1.x.x : Increment this field when there is a major format change
  # Minor Version x.1.x : Increment this field when there is a minor change that breaks backward
  #   compatibility for an existing field or a field is removed.
  # Patch version x.x.1 : Increment this field when a minor format change that just adds information
  #   that an application can safely ignore.
  #
  # Note format changes in src/python/pants/docs/export.md and update the Changelog section.
  #
  DEFAULT_EXPORT_VERSION = '1.0.4'

  @classmethod
  def subsystem_dependencies(cls):
    return super(Export, cls).subsystem_dependencies() + (DistributionLocator, JvmPlatform)

  class SourceRootTypes(object):
    """Defines SourceRoot Types Constants"""
    SOURCE = 'SOURCE'  # Source Target
    TEST = 'TEST'  # Test Target
    SOURCE_GENERATED = 'SOURCE_GENERATED'  # Code Gen Source Targets
    EXCLUDED = 'EXCLUDED'  # Excluded Target
    RESOURCE = 'RESOURCE'  # Resource belonging to Source Target
    TEST_RESOURCE = 'TEST_RESOURCE'  # Resource belonging to Test Target

  @staticmethod
  def _is_jvm(dep):
    return dep.is_jvm or isinstance(dep, JvmApp)

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

  @classmethod
  def register_options(cls, register):
    super(Export, cls).register_options(register)
    register('--formatted', default=True, action='store_false',
             help='Causes output to be a single line of JSON.')
    register('--libraries', default=True, action='store_true',
             help='Causes libraries to be output.')
    register('--libraries-sources', default=False, action='store_true',
             help='Causes libraries with sources to be output.')
    register('--libraries-javadocs', default=False, action='store_true',
             help='Causes libraries with javadocs to be output.')
    register('--sources', default=False, action='store_true',
             help='Causes sources to be output.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(Export, cls).prepare(options, round_manager)
    if options.libraries or options.libraries_sources or options.libraries_javadocs:
      # TODO(John Sirois): Clean this up by using IvyUtils in here, passing it the confs we need
      # as a parameter.
      # See: https://github.com/pantsbuild/pants/issues/2177
      round_manager.require_data('compile_classpath')

      # NB: These are fake products that only serve as signals to the upstream producer of
      # 'compile_classpath' to resolve extra classifiers (ivy confs).  A hack that can go away with
      # execution of the TODO above.
      round_manager.require('jar_map_default')
      if options.libraries_sources:
        round_manager.require('jar_map_sources')
      if options.libraries_javadocs:
        round_manager.require('jar_map_javadoc')

  def __init__(self, *args, **kwargs):
    super(Export, self).__init__(*args, **kwargs)
    self.format = self.get_options().formatted

  def console_output(self, targets):
    targets_map = {}
    resource_target_map = {}
    classpath_products = (self.context.products.get_data('compile_classpath')
                          if self.get_options().libraries else None)

    python_interpreter_targets_mapping = defaultdict(list)

    def process_target(current_target):
      """
      :type current_target:pants.build_graph.target.Target
      """
      def get_target_type(target):
        if target.is_test:
          return Export.SourceRootTypes.TEST
        else:
          if (isinstance(target, Resources) and
              target in resource_target_map and
              resource_target_map[target].is_test):
            return Export.SourceRootTypes.TEST_RESOURCE
          elif isinstance(target, Resources):
            return Export.SourceRootTypes.RESOURCE
          else:
            return Export.SourceRootTypes.SOURCE

      info = {
        'targets': [],
        'libraries': [],
        'roots': [],
        'target_type': get_target_type(current_target),
        'is_code_gen': current_target.is_codegen,
        'pants_target_type': self._get_pants_target_alias(type(current_target))
      }

      if not current_target.is_synthetic:
        info['globs'] = current_target.globs_relative_to_buildroot()
        if self.get_options().sources:
          info['sources'] = list(current_target.sources_relative_to_buildroot())

      if isinstance(current_target, PythonRequirementLibrary):
        reqs = current_target.payload.get_field_value('requirements', set())
        """:type : set[pants.backend.python.python_requirement.PythonRequirement]"""
        info['requirements'] = [req.key for req in reqs]

      if isinstance(current_target, PythonTarget):
        interpreter_for_target = self.select_interpreter_for_targets([current_target])
        if interpreter_for_target is None:
          raise TaskError('Unable to find suitable interpreter for {}'
                          .format(current_target.address))
        python_interpreter_targets_mapping[interpreter_for_target].append(current_target)
        info['python_interpreter'] = str(interpreter_for_target.identity)

      def iter_transitive_jars(jar_lib):
        """
        :type jar_lib: :class:`pants.backend.jvm.targets.jar_library.JarLibrary`
        :rtype: :class:`collections.Iterator` of
                :class:`pants.backend.jvm.jar_dependency_utils.M2Coordinate`
        """
        if classpath_products:
          jar_products = classpath_products.get_artifact_classpath_entries_for_targets((jar_lib,))
          for _, jar_entry in jar_products:
            coordinate = jar_entry.coordinate
            # We drop classifier and type_ since those fields are represented in the global
            # libraries dict and here we just want the key into that dict (see `_jar_id`).
            yield M2Coordinate(org=coordinate.org, name=coordinate.name, rev=coordinate.rev)

      target_libraries = OrderedSet()
      if isinstance(current_target, JarLibrary):
        target_libraries = OrderedSet(iter_transitive_jars(current_target))
      for dep in current_target.dependencies:
        info['targets'].append(dep.address.spec)
        if isinstance(dep, JarLibrary):
          for jar in dep.jar_dependencies:
            target_libraries.add(M2Coordinate(jar.org, jar.name, jar.rev))
          # Add all the jars pulled in by this jar_library
          target_libraries.update(iter_transitive_jars(dep))
        if isinstance(dep, Resources):
          resource_target_map[dep] = current_target

      if isinstance(current_target, ScalaLibrary):
        for dep in current_target.java_sources:
          info['targets'].append(dep.address.spec)
          process_target(dep)

      if isinstance(current_target, JvmTarget):
        info['excludes'] = [self._exclude_id(exclude) for exclude in current_target.excludes]
        info['platform'] = current_target.platform.name

      info['roots'] = map(lambda (source_root, package_prefix): {
        'source_root': source_root,
        'package_prefix': package_prefix
      }, self._source_roots_for_target(current_target))

      if classpath_products:
        info['libraries'] = [self._jar_id(lib) for lib in target_libraries]
      targets_map[current_target.address.spec] = info

    for target in targets:
      process_target(target)

    jvm_platforms_map = {
      'default_platform' : JvmPlatform.global_instance().default_platform.name,
      'platforms': {
        str(platform_name): {
          'target_level' : str(platform.target_level),
          'source_level' : str(platform.source_level),
          'args' : platform.args,
        } for platform_name, platform in JvmPlatform.global_instance().platforms_by_name.items() }
    }

    graph_info = {
      'version': self.DEFAULT_EXPORT_VERSION,
      'targets': targets_map,
      'jvm_platforms': jvm_platforms_map,
    }
    jvm_distributions = DistributionLocator.global_instance().all_jdk_paths()
    if jvm_distributions:
      graph_info['jvm_distributions'] = jvm_distributions

    if classpath_products:
      graph_info['libraries'] = self._resolve_jars_info(targets, classpath_products)

    if python_interpreter_targets_mapping:
      interpreters = self.interpreter_cache.select_interpreter(
        python_interpreter_targets_mapping.keys())
      default_interpreter = interpreters[0]

      interpreters_info = {}
      for interpreter, targets in six.iteritems(python_interpreter_targets_mapping):
        chroot = self.cached_chroot(
          interpreter=interpreter,
          pex_info=PexInfo.default(),
          targets=targets
        )
        interpreters_info[str(interpreter.identity)] = {
          'binary': interpreter.binary,
          'chroot': chroot.path()
        }

      graph_info['python_setup'] = {
        'default_interpreter': str(default_interpreter.identity),
        'interpreters': interpreters_info
      }

    if self.format:
      return json.dumps(graph_info, indent=4, separators=(',', ': ')).splitlines()
    else:
      return [json.dumps(graph_info)]

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

  @memoized_property
  def target_aliases_map(self):
    registered_aliases = self.context.build_file_parser.registered_aliases()
    map = {}
    for alias, target_types in registered_aliases.target_types_by_alias.items():
      # If a target class is registered under multiple aliases returns the last one.
      for target_type in target_types:
        map[target_type] = alias
    return map

  def _get_pants_target_alias(self, pants_target_type):
    """Returns the pants target alias for the given target"""
    if pants_target_type in self.target_aliases_map:
      return self.target_aliases_map.get(pants_target_type)
    else:
      raise TaskError('Unregistered target type {target_type}'
                      .format(target_type=pants_target_type))

  @staticmethod
  def _source_roots_for_target(target):
    """
    :type target:pants.build_graph.target.Target
    """
    def root_package_prefix(source_file):
      source = os.path.dirname(source_file)
      return os.path.join(get_buildroot(), target.target_base, source), source.replace(os.sep, '.')
    return set(map(root_package_prefix, target.sources_relative_to_source_root()))
