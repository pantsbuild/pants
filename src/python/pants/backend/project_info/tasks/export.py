# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from collections import defaultdict

from twitter.common.collections import OrderedSet

from pants.backend.core.targets.resources import Resources
from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.ivy_utils import IvyModuleRef
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.project_info.tasks.ide_gen import IdeGen
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError


# Changing the behavior of this task may affect the IntelliJ Pants plugin
# Please add fkorotkov, tdesai to reviews for this file
class Export(ConsoleTask):
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
  DEFAULT_EXPORT_VERSION='1.0.0'

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
    if jar.rev:
      return '{0}:{1}:{2}'.format(jar.org, jar.name, jar.rev)
    else:
      return '{0}:{1}'.format(jar.org, jar.name)

  @staticmethod
  def _address(address):
    """
    :type address: pants.base.address.SyntheticAddress
    """
    return '{0}:{1}'.format(address.spec_path, address.target_name)

  @classmethod
  def register_options(cls, register):
    super(Export, cls).register_options(register)
    register('--formatted', default=True, action='store_false',
             help='Causes output to be a single line of JSON.')
    register('--libraries', default=True, action='store_true',
             help='Causes libraries to be output.')
    register('--sources', default=False, action='store_true',
             help='Causes sources to be output.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(Export, cls).prepare(options, round_manager)
    if options.libraries:
      round_manager.require_data('ivy_jar_products')

  def __init__(self, *args, **kwargs):
    super(Export, self).__init__(*args, **kwargs)
    self.format = self.get_options().formatted
    self.target_aliases_map = None

  def console_output(self, targets):
    targets_map = {}
    resource_target_map = {}
    if self.get_options().libraries:
      ivy_jar_products = self.context.products.get_data('ivy_jar_products') or {}
      # This product is a list for historical reasons (exclusives groups) but in practice should
      # have either 0 or 1 entries.
      ivy_info_list = ivy_jar_products.get('default')
      if ivy_info_list:
        assert len(ivy_info_list) == 1, (
          'The values in ivy_jar_products should always be length 1,'
          ' since we no longer have exclusives groups.'
        )
        ivy_info = ivy_info_list[0]
      else:
        ivy_info = None

    ivy_jar_memo = {}
    def process_target(current_target):
      """
      :type current_target:pants.base.target.Target
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

      def get_transitive_jars(jar_lib):
        if not self.get_options().libraries:
          return []
        if not ivy_info:
          return OrderedSet()
        transitive_jars = OrderedSet()
        for jar in jar_lib.jar_dependencies:
          transitive_jars.update(ivy_info.get_jars_for_ivy_module(jar, memo=ivy_jar_memo))
        return transitive_jars

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

      target_libraries = set()
      if isinstance(current_target, JarLibrary):
        target_libraries = get_transitive_jars(current_target)
      for dep in current_target.dependencies:
        info['targets'].append(self._address(dep.address))
        if isinstance(dep, JarLibrary):
          for jar in dep.jar_dependencies:
            target_libraries.add(IvyModuleRef(jar.org, jar.name, jar.rev))
          # Add all the jars pulled in by this jar_library
          target_libraries.update(get_transitive_jars(dep))
        if isinstance(dep, Resources):
          resource_target_map[dep] = current_target

      if isinstance(current_target, ScalaLibrary):
        for dep in current_target.java_sources:
          info['targets'].append(self._address(dep.address))
          process_target(dep)

      info['roots'] = map(lambda (source_root, package_prefix): {
        'source_root': source_root,
        'package_prefix': package_prefix
      }, self._source_roots_for_target(current_target))

      if self.get_options().libraries:
        info['libraries'] = [self._jar_id(lib) for lib in target_libraries]
      targets_map[self._address(current_target.address)] = info

    for target in targets:
      process_target(target)

    graph_info = {
      'targets': targets_map,
    }
    if self.get_options().libraries:
      graph_info['libraries'] = self._resolve_jars_info()

    graph_info['version'] = self.DEFAULT_EXPORT_VERSION

    if self.format:
      return json.dumps(graph_info, indent=4, separators=(',', ': ')).splitlines()
    else:
      return [json.dumps(graph_info)]

  def _resolve_jars_info(self):
    mapping = defaultdict(list)
    jar_data = self.context.products.get_data('ivy_jar_products')
    jar_infos = IdeGen.get_jar_infos(ivy_products=jar_data, confs=['default', 'sources', 'javadoc'])
    for jar, paths in jar_infos.iteritems():
      mapping[self._jar_id(jar)] = paths
    return mapping

  def _get_pants_target_alias(self, pants_target_type):
    """Returns the pants target alias for the given target"""
    if not self.target_aliases_map:
      target_aliases = self.context.build_file_parser.registered_aliases().targets
      # If a target class is registered under multiple aliases returns the last one.
      self.target_aliases_map = {classname: alias for alias, classname in target_aliases.items()}
    if pants_target_type in self.target_aliases_map:
      return self.target_aliases_map.get(pants_target_type)
    else:
      raise TaskError('Unregistered target type {target_type}'.format(target_type=pants_target_type))

  @staticmethod
  def _source_roots_for_target(target):
    """
    :type target:pants.base.target.Target
    """
    def root_package_prefix(source_file):
      source = os.path.dirname(source_file)
      return os.path.join(get_buildroot(), target.target_base, source), source.replace(os.sep, '.')
    return set(map(root_package_prefix, target.sources_relative_to_source_root()))
