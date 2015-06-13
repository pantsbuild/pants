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
    super(Depmap, cls).register_options(register)
    register('--internal-only', default=False, action='store_true',
             help='Specifies that only internal dependencies should be included in the graph '
                  'output (no external jars).')
    register('--external-only', default=False, action='store_true',
             help='Specifies that only external dependencies should be included in the graph '
                  'output (only external jars).')
    register('--minimal', default=False, action='store_true',
             help='For a textual dependency tree, only prints a dependency the 1st '
                  'time it is encountered.  For graph output this does nothing.')
    register('--graph', default=False, action='store_true',
             help='Specifies the internal dependency graph should be output in the dot digraph '
                  'format.')
    register('--separator', default='-',
             help='Specifies the separator to use between the org/name/rev components of a '
                  'dependency\'s fully qualified name.')
    register('--path-to',
             help='Show only items on the path to the given target.')

  def __init__(self, *args, **kwargs):
    super(Depmap, self).__init__(*args, **kwargs)

    self.is_internal_only = self.get_options().internal_only
    self.is_external_only = self.get_options().external_only

    if self.is_internal_only and self.is_external_only:
      raise TaskError('At most one of --internal-only or --external-only can be selected.')

    self.is_minimal = self.get_options().minimal
    self.is_graph = self.get_options().graph
    self.path_to = self.get_options().path_to
    self.separator = self.get_options().separator
    self.target_aliases_map = None

  def console_output(self, targets):
    if len(self.context.target_roots) == 0:
      raise TaskError("One or more target addresses are required.")
    for target in self.context.target_roots:
      if self.is_graph:
        for line in self._output_digraph(target):
          yield line
      else:
        for line in self._output_dependency_tree(target):
          yield line

  def _dep_id(self, dependency):
    """Returns a tuple of dependency_id , is_internal_dep."""

    params = dict(sep=self.separator)
    if isinstance(dependency, JarDependency):
      params.update(org=dependency.org, name=dependency.name, rev=dependency.rev)
    else:
      params.update(org='internal', name=dependency.id)

    if params.get('rev'):
      return "{org}{sep}{name}{sep}{rev}".format(**params), False
    else:
      return "{org}{sep}{name}".format(**params), True

  def _output_dependency_tree(self, target):
    def output_dep(dep, indent):
      return "{}{}".format(indent * "  ", dep)

    def check_path_to(jar_dep_id):
      """
      Check that jar_dep_id is the dep we are looking for with path_to
      (or that path_to is not enabled)
      """
      return jar_dep_id == self.path_to or not self.path_to

    def output_deps(dep, indent=0, outputted=set()):
      dep_id, _ = self._dep_id(dep)
      if dep_id in outputted:
        return [output_dep("*{}".format(dep_id), indent)] if not self.is_minimal else []
      else:
        output = []
        if not self.is_external_only:
          indent += 1

        jar_output = []
        if not self.is_internal_only:
          if self._is_jvm(dep):
            for jar_dep in dep.jar_dependencies:
              jar_dep_id, internal = self._dep_id(jar_dep)
              if not internal:
                if jar_dep_id not in outputted or (not self.is_minimal
                                                   and not self.is_external_only):
                  if check_path_to(jar_dep_id):
                    jar_output.append(output_dep(jar_dep_id, indent))
                  outputted.add(jar_dep_id)

        dep_output = []
        for internal_dep in dep.dependencies:
          dep_output.extend(output_deps(internal_dep, indent, outputted))

        if not check_path_to(dep_id) and not (jar_output or dep_output):
          return []

        if not self.is_external_only:
          output.append(output_dep(dep_id, indent - 1))
          outputted.add(dep_id)

        output.extend(dep_output)
        output.extend(jar_output)
        return output
    return output_deps(target)

  def _output_digraph(self, target):
    color_by_type = {}

    def output_candidate(internal):
      return ((self.is_internal_only and internal)
               or (self.is_external_only and not internal)
               or (not self.is_internal_only and not self.is_external_only))

    def output_dep(dep):
      dep_id, internal = self._dep_id(dep)
      if internal:
        fmt = '  "{id}" [style=filled, fillcolor="{color}"];'
      else:
        fmt = '  "{id}" [style=filled, fillcolor="{color}", shape=ellipse];'
      if type(dep) not in color_by_type:
        color_by_type[type(dep)] = len(color_by_type.keys()) + 1
      return fmt.format(id=dep_id, color=color_by_type[type(dep)])

    def output_deps(outputted, dep, parent=None):
      output = []

      if dep not in outputted:
        outputted.add(dep)
        output.append(output_dep(dep))
        if parent:
          output.append('  "{}" -> "{}";'.format(self._dep_id(parent)[0], self._dep_id(dep)[0]))

        # TODO: This is broken. 'dependency' doesn't exist here, and we don't have
        # internal_dependencies any more anyway.
        if self._is_jvm(dependency):
          for internal_dependency in dependency.internal_dependencies:
            output += output_deps(outputted, internal_dependency, dependency)

        for jar in (dependency.jar_dependencies if self._is_jvm(dependency) else [dependency]):
          jar_id, internal = self._dep_id(jar)
          if output_candidate(internal):
            if jar not in outputted:
              output += [output_dep(jar)]
              outputted.add(jar)

            target_id, _ = self._dep_id(target)
            dep_id, _ = self._dep_id(dependency)
            left_id = target_id if self.is_external_only else dep_id
            if (left_id, jar_id) not in outputted:
              styled = internal and not self.is_internal_only
              output += ['  "{}" -> "{}"{};'.format(left_id, jar_id,
                                                    ' [style="dashed"]' if styled else '')]
              outputted.add((left_id, jar_id))
      return output
    header = ['digraph "{}" {{'.format(target.id)]
    graph_attr = ['  node [shape=rectangle, colorscheme=set312;];', '  rankdir=LR;']
    return header + graph_attr + output_deps(set(), target) + ['}']
