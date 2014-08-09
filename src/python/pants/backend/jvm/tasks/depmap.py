# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)
from collections import defaultdict
import json
import os

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError

# Changing the behavior of this task may affect the IntelliJ Pants plugin
# Please add fkorotkov or ajohnson to reviews for this file
# XXX(pl): JVM hairball violator
class Depmap(ConsoleTask):
  """Generates either a textual dependency tree or a graphviz digraph dot file for the dependency
  set of a target.
  """

  @staticmethod
  def _is_jvm(dep):
    return dep.is_jvm or dep.is_jvm_app

  @staticmethod
  def _jar_id(jar):
    #return '{0}:{1}:{2}'.format(jar.org, jar.name, jar.rev) if jar.rev else '{0}:{1}'.format(jar.org, jar.name)
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
  def setup_parser(cls, option_group, args, mkflag):
    super(Depmap, cls).setup_parser(option_group, args, mkflag)

    cls.internal_only_flag = mkflag("internal-only")
    cls.external_only_flag = mkflag("external-only")
    option_group.add_option(cls.internal_only_flag,
                            action="store_true",
                            dest="depmap_is_internal_only",
                            default=False,
                            help='Specifies that only internal dependencies should'
                                 ' be included in the graph output (no external jars).')
    option_group.add_option(cls.external_only_flag,
                            action="store_true",
                            dest="depmap_is_external_only",
                            default=False,
                            help='Specifies that only external dependencies should'
                            ' be included in the graph output (only external jars).')
    option_group.add_option(mkflag("minimal"),
                            action="store_true",
                            dest="depmap_is_minimal",
                            default=False,
                            help='For a textual dependency tree, only prints a dependency the 1st'
                                 ' time it is encountered.  For graph output this does nothing.')
    option_group.add_option(mkflag("separator"),
                            dest="depmap_separator",
                            default="-",
                            help='Specifies the separator to use between the org/name/rev'
                                 ' components of a dependency\'s fully qualified name.')
    option_group.add_option(mkflag("graph"),
                            action="store_true",
                            dest="depmap_is_graph",
                            default=False,
                            help='Specifies the internal dependency graph should be'
                                 ' output in the dot digraph format')
    option_group.add_option(mkflag("project-info"),
                            action="store_true",
                            dest="depmap_is_project_info",
                            default=False,
                            help='Produces a json object with info about the target,'
                                 ' including source roots, dependencies, and paths to'
                                 ' libraries for their targets and dependencies.')
    option_group.add_option(mkflag("project-info-formatted"),
                            action="store_false",
                            dest="depmap_is_formatted",
                            default=True,
                            help='Causes project-info output to be a single line of JSON')


  def __init__(self, *args, **kwargs):
    super(Depmap, self).__init__(*args, **kwargs)
    # Require information about jars
    self.context.products.require_data('ivy_jar_products')

    if (self.context.options.depmap_is_internal_only
        and self.context.options.depmap_is_external_only):
      cls = self.__class__
      error_str = "At most one of %s or %s can be selected." % (cls.internal_only_flag,
                                                                      cls.external_only_flag)
      raise TaskError(error_str)

    self.is_internal_only = self.context.options.depmap_is_internal_only
    self.is_external_only = self.context.options.depmap_is_external_only
    self.is_minimal = self.context.options.depmap_is_minimal
    self.is_graph = self.context.options.depmap_is_graph
    self.separator = self.context.options.depmap_separator
    self.project_info = self.context.options.depmap_is_project_info
    self.format = self.context.options.depmap_is_formatted

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
      if self._is_jvm(target) or isinstance(target, Dependencies):
        if self.is_graph:
          for line in self._output_digraph(target):
            yield line
        else:
          for line in self._output_dependency_tree(target):
            yield line
      elif target.is_python:
        raise TaskError('Unsupported for Python targets')
      else:
        raise TaskError('Unsupported for target %s' % target)

  def _dep_id(self, dependency):
    """Returns a tuple of dependency_id , is_internal_dep."""

    params = dict(sep=self.separator)
    if isinstance(dependency, JarDependency):
      params.update(org=dependency.org, name=dependency.name, rev=dependency.rev)
    else:
      params.update(org='internal', name=dependency.id)

    if params.get('rev'):
      return "%(org)s%(sep)s%(name)s%(sep)s%(rev)s" % params, False
    else:
      return "%(org)s%(sep)s%(name)s" % params, True

  def _output_dependency_tree(self, target):
    def output_dep(dep, indent):
      return "%s%s" % (indent * "  ", dep)

    def output_deps(dep, indent=0, outputted=set()):
      dep_id, _ = self._dep_id(dep)
      if dep_id in outputted:
        return [output_dep("*%s" % dep_id, indent)] if not self.is_minimal else []
      else:
        output = []
        if not self.is_external_only:
          output += [output_dep(dep_id, indent)]
          outputted.add(dep_id)
          indent += 1

        if self._is_jvm(dep) or isinstance(dep, Dependencies):
          for internal_dep in dep.dependencies:
            output += output_deps(internal_dep, indent, outputted)

        if not self.is_internal_only:
          if self._is_jvm(dep):
            for jar_dep in dep.jar_dependencies:
              jar_dep_id, internal = self._dep_id(jar_dep)
              if not internal:
                if jar_dep_id not in outputted or (not self.is_minimal
                                                   and not self.is_external_only):
                  output += [output_dep(jar_dep_id, indent)]
                  outputted.add(jar_dep_id)
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
        fmt = '  "%(id)s" [style=filled, fillcolor="%(color)d"];'
      else:
        fmt = '  "%(id)s" [style=filled, fillcolor="%(color)d", shape=ellipse];'
      if not color_by_type.has_key(type(dep)):
        color_by_type[type(dep)] = len(color_by_type.keys()) + 1
      return fmt % {'id': dep_id, 'color': color_by_type[type(dep)]}

    def output_deps(outputted, dep, parent=None):
      output = []

      if dep not in outputted:
        outputted.add(dep)
        output.append(output_dep(dep))
        if parent:
          output.append('  "%s" -> "%s";' % (self._dep_id(parent)[0], self._dep_id(dep)[0]))

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
              output += ['  "%s" -> "%s"%s;' % (left_id, jar_id,
                                                ' [style="dashed"]' if styled else '')]
              outputted.add((left_id, jar_id))
      return output
    header = ['digraph "%s" {' % target.id]
    graph_attr = ['  node [shape=rectangle, colorscheme=set312;];', '  rankdir=LR;']
    return header + graph_attr + output_deps(set(), target) + ['}']

  def project_info_output(self, targets):
    targets_map = {}

    def process_target(current_target):
      """
      :type current_target:pants.base.target.Target
      """

      info = {
        'targets': [],
        'libraries': [],
        'roots': [],
        'test_target': current_target.is_test
      }

      for dep in current_target.dependencies:
        if dep.is_java or dep.is_jar_library or dep.is_jvm or dep.is_scala or dep.is_scalac_plugin:
          info['targets'].append(self._address(dep.address))

        if dep.is_jar_library:
          for jar in dep.jar_dependencies:
            info['libraries'].append(self._jar_id(jar))

      roots = list(set(
        [os.path.dirname(source) for source in current_target.sources_relative_to_source_root()]
      ))
      info['roots'] = map(lambda source: {
        'source_root': os.path.join(get_buildroot(), current_target.target_base, source),
        'package_prefix': source.replace(os.sep, '.')
      }, roots)
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

