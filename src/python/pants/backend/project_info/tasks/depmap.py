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
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_app import JvmApp
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.base.build_environment import get_buildroot
from pants.base.deprecated import deprecated
from pants.base.exceptions import TaskError


class Depmap(ConsoleTask):
  """Generates either a textual dependency tree or a graphviz digraph dot file for the dependency
  set of a target.
  """
  class SourceRootTypes(object):
    """Defines SourceRoot Types Constants"""
    SOURCE = 'SOURCE'  # Source Target
    TEST = 'TEST'  # Test Target
    SOURCE_GENERATED = 'SOURCE_GENERATED'  # Code Gen Source Targets
    EXCLUDED = 'EXCLUDED'  # Excluded Target
    RESOURCE = 'RESOURCE'  # Resource belonging to Source Target
    TEST_RESOURCE = 'TEST_RESOURCE'  # Resource belonging to Test Target

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
    super(Depmap, cls).register_options(register)
    register('--internal-only', default=False, action='store_true',
             help='Specifies that only internal dependencies should be included in the graph '
                  'output (no external jars).')
    register('--external-only', default=False, action='store_true',
             help='Specifies that only external dependencies should be included in the graph '
                  'output (only external jars).')
    register('--minimal', default=False, action='store_true',
             help='For a textual dependency tree, only prints a dependency the 1st '
                  'time it is encountered. This is a no-op for --graph.')
    register('--graph', default=False, action='store_true',
             help='Specifies the internal dependency graph should be output in the dot digraph '
                  'format.')
    register('--tree', default=False, action='store_true',
             help='For text output, show an ascii tree to help visually line up indentions.')
    register('--show-types', default=False, action='store_true',
             help='Show types of objects in depmap.')
    register('--project-info', default=False, action='store_true',
             deprecated_version='0.0.33',
             deprecated_hint='Use the export goal instead of depmap to get info for the IDE.',
             help='Produces a json object with info about the target, including source roots, '
                  'dependencies, and paths to libraries for their targets and dependencies.')
    register('--project-info-formatted', default=True, action='store_false',
             deprecated_version='0.0.33',
             deprecated_hint='Use the export goal instead of depmap to get info for the IDE.',
             help='Causes project-info output to be a single line of JSON.')
    register('--separator', default='-',
             help='Specifies the separator to use between the org/name/rev components of a '
                  'dependency\'s fully qualified name.')
    register('--path-to',
             help='Show only items on the path to the given target. This is a no-op for --graph.')

  @classmethod
  def prepare(cls, options, round_manager):
    super(Depmap, cls).prepare(options, round_manager)
    if options.project_info:
      # Require information about jars
      round_manager.require_data('ivy_jar_products')

  def __init__(self, *args, **kwargs):
    super(Depmap, self).__init__(*args, **kwargs)

    self.is_internal_only = self.get_options().internal_only
    self.is_external_only = self.get_options().external_only

    if self.is_internal_only and self.is_external_only:
      raise TaskError('At most one of --internal-only or --external-only can be selected.')

    self.is_minimal = self.get_options().minimal
    self.is_graph = self.get_options().graph
    self.should_tree = self.get_options().tree
    self.show_types = self.get_options().show_types
    self.path_to = self.get_options().path_to
    self.separator = self.get_options().separator
    self.project_info = self.get_options().project_info
    self.format = self.get_options().project_info_formatted
    self.target_aliases_map = None

  def console_output(self, targets):
    if len(self.context.target_roots) == 0:
      raise TaskError("One or more target addresses are required.")

    if self.project_info and self.is_graph:
      raise TaskError('-graph and -project-info are mutually exclusive; please choose one.')

    if self.project_info:
      output = self.project_info_output(targets)
      for line in output:
        yield line
      return

    for target in self.context.target_roots:
      out = self._output_digraph(target) if self.is_graph else self._output_dependency_tree(target)
      for line in out:
        yield line

  def _dep_id(self, dependency):
    """Returns a tuple of dependency_id , is_internal_dep."""

    params = dict(sep=self.separator)
    if isinstance(dependency, JarDependency):
      params.update(org=dependency.org, name=dependency.name, rev=dependency.rev)
    else:
      params.update(org='internal', name=dependency.id)

    if params.get('rev') is not None:
      return "{org}{sep}{name}{sep}{rev}".format(**params), False
    else:
      return "{org}{sep}{name}".format(**params), True

  def _enumerate_visible_deps(self, dep, predicate):
    dep_id, internal = self._dep_id(dep)

    dependencies = sorted([x for x in getattr(dep, 'dependencies', [])]) + sorted(
      [x for x in getattr(dep, 'jar_dependencies', [])] if not self.is_internal_only else [])

    for inner_dep in dependencies:
      dep_id, internal = self._dep_id(inner_dep)
      if predicate(internal):
        yield inner_dep

  def output_candidate(self, internal):
    return ((not self.is_internal_only and not self.is_external_only)
            or (self.is_internal_only and internal)
            or (self.is_external_only and not internal))

  def _output_dependency_tree(self, target):
    """Plain-text depmap output handler."""

    def make_line(dep, indent, is_dupe=False):
      indent_join, indent_chars = ('--', '  |') if self.should_tree else ('', '  ')
      dupe_char = '*' if is_dupe else ''
      return '{}{}{}{}'.format(indent * indent_chars, indent_join, dupe_char, dep)

    def output_deps(dep, indent, outputted, stack):
      dep_id, internal = self._dep_id(dep)

      if self.path_to:
        if dep_id == self.path_to:
          for dep_id, indent in stack + [(dep_id, indent)]:
            yield make_line(dep_id, indent)
          return
      else:
        if not (dep_id in outputted and self.is_minimal):
          yield make_line(dep_id, indent, is_dupe=dep_id in outputted)
          outputted.add(dep_id)

      for sub_dep in self._enumerate_visible_deps(dep, self.output_candidate):
        for item in output_deps(sub_dep, indent + 1, outputted, stack + [(dep_id, indent)]):
          yield item

    for item in output_deps(target, 0, set(), []):
      yield item

  def _output_digraph(self, target):
    """Graphviz format depmap output handler."""
    color_by_type = {}

    def maybe_add_type(dep, dep_id):
      """Add a class type to a dependency id if --show-types is passed."""
      return dep_id if not self.show_types else '\\n'.join((dep_id, dep.__class__.__name__))

    def make_node(dep, dep_id, internal):
      line_fmt = '  "{id}" [style=filled, fillcolor={color}{internal}];'
      int_shape = ', shape=ellipse' if not internal else ''

      dep_class = dep.__class__.__name__
      if dep_class not in color_by_type:
        color_by_type[dep_class] = len(color_by_type.keys()) + 1

      return line_fmt.format(id=dep_id, internal=int_shape, color=color_by_type[dep_class])

    def make_edge(from_dep_id, to_dep_id):
      return '  "{}" -> "{}";'.format(from_dep_id, to_dep_id)

    def output_deps(dep, parent, parent_id, outputted):
      dep_id, internal = self._dep_id(dep)

      if dep_id not in outputted:
        yield make_node(dep, maybe_add_type(dep, dep_id), internal)
        outputted.add(dep_id)

      if parent:
        edge_id = (parent_id, dep_id)
        if edge_id not in outputted:
          yield make_edge(maybe_add_type(parent, parent_id), maybe_add_type(dep, dep_id))
          outputted.add(edge_id)

      for sub_dep in self._enumerate_visible_deps(dep, self.output_candidate):
        for item in output_deps(sub_dep, dep, dep_id, outputted):
          yield item

    yield 'digraph "{}" {{'.format(target.id)
    yield '  node [shape=rectangle, colorscheme=set312;];'
    yield '  rankdir=LR;'
    for line in output_deps(target, parent=None, parent_id=None, outputted=set()):
      yield line
    yield '}'

  @deprecated(removal_version='0.0.33',
      hint_message='Information from "depmap --project-info" should now be accessed through the "export" goal')
  def project_info_output(self, targets):
    targets_map = {}
    resource_target_map = {}
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
          return Depmap.SourceRootTypes.TEST
        else:
          if (isinstance(target, Resources) and
              target in resource_target_map and
              resource_target_map[target].is_test):
            return Depmap.SourceRootTypes.TEST_RESOURCE
          elif isinstance(target, Resources):
            return Depmap.SourceRootTypes.RESOURCE
          else:
            return Depmap.SourceRootTypes.SOURCE

      def get_transitive_jars(jar_lib):
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

      info['libraries'] = [self._jar_id(lib) for lib in target_libraries]
      targets_map[self._address(current_target.address)] = info

    for target in targets:
      process_target(target)

    graph_info = {
      'targets': targets_map,
      'libraries': self._resolve_jars_info()
    }
    if self.format:
      return json.dumps(graph_info, indent=4, separators=(',', ': ')).splitlines()
    else:
      return [json.dumps(graph_info)]

  def _resolve_jars_info(self):
    mapping = defaultdict(list)
    jar_data = self.context.products.get_data('ivy_jar_products')
    if not jar_data:
      return mapping
    for dep in jar_data['default']:
      for module in dep.modules_by_ref.values():
        mapping[self._jar_id(module.ref)] = [artifact.path for artifact in module.artifacts]
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
