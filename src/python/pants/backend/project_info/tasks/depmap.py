# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.jvm.targets.jar_dependency import JarDependency
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
             help='Show types of objects in depmap --graph.')
    register('--separator', default='-',
             help='Specifies the separator to use between the org/name/rev components of a '
                  'dependency\'s fully qualified name.')
    register('--path-to',
             help='Show only items on the path to the given target. This is a no-op for --graph.')

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
    self.target_aliases_map = None

  def console_output(self, targets):
    if len(self.context.target_roots) == 0:
      raise TaskError("One or more target addresses are required.")

    for target in self.context.target_roots:
      out = self._output_digraph(target) if self.is_graph else self._output_dependency_tree(target)
      for line in out:
        yield line

  def _dep_id(self, dependency):
    """Returns a tuple of dependency_id, is_internal_dep."""
    params = dict(sep=self.separator)

    if isinstance(dependency, JarDependency):
      # TODO(kwilson): handle 'classifier' and 'type'.
      params.update(org=dependency.org, name=dependency.name, rev=dependency.rev)
      is_internal_dep = False
    else:
      params.update(org='internal', name=dependency.id)
      is_internal_dep = True

    return ('{org}{sep}{name}{sep}{rev}' if params.get('rev') else
            '{org}{sep}{name}').format(**params), is_internal_dep

  def _enumerate_visible_deps(self, dep, predicate):
    # We present the dependencies out of classpath order and instead in alphabetized internal deps,
    # then alphabetized external deps order for ease in scanning output.
    dependencies = sorted(x for x in getattr(dep, 'dependencies', []))
    if not self.is_internal_only:
      dependencies.extend(sorted((x for x in getattr(dep, 'jar_dependencies', [])),
                                 key=lambda x: (x.org, x.name, x.rev, x.classifier)))
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
      return ''.join((indent * indent_chars, indent_join, dupe_char, dep))

    def output_deps(dep, indent, outputted, stack):
      dep_id, internal = self._dep_id(dep)

      if self.is_minimal and dep_id in outputted:
        return

      if self.path_to:
        # If we hit the search target from self.path_to, yield the stack items and bail.
        if dep_id == self.path_to:
          for dep_id, indent in stack + [(dep_id, indent)]:
            yield make_line(dep_id, indent)
          return
      else:
        if self.output_candidate(internal):
          yield make_line(dep_id,
                          0 if self.is_external_only else indent,
                          is_dupe=dep_id in outputted)
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

    def make_edge(from_dep_id, to_dep_id, internal):
      style = ' [style=dashed]' if not internal else ''
      return '  "{}" -> "{}"{};'.format(from_dep_id, to_dep_id, style)

    def output_deps(dep, parent, parent_id, outputted):
      dep_id, internal = self._dep_id(dep)

      if dep_id not in outputted:
        yield make_node(dep, maybe_add_type(dep, dep_id), internal)
        outputted.add(dep_id)

        for sub_dep in self._enumerate_visible_deps(dep, self.output_candidate):
          for item in output_deps(sub_dep, dep, dep_id, outputted):
            yield item

      if parent:
        edge_id = (parent_id, dep_id)
        if edge_id not in outputted:
          yield make_edge(maybe_add_type(parent, parent_id), maybe_add_type(dep, dep_id), internal)
          outputted.add(edge_id)

    yield 'digraph "{}" {{'.format(target.id)
    yield '  node [shape=rectangle, colorscheme=set312;];'
    yield '  rankdir=LR;'
    for line in output_deps(target, parent=None, parent_id=None, outputted=set()):
      yield line
    yield '}'
