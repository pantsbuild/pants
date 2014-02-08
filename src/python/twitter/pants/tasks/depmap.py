# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from __future__ import print_function

from twitter.pants.tasks.console_task import ConsoleTask
from twitter.pants.tasks import TaskError

from twitter.pants.targets.jar_dependency import JarDependency


class Depmap(ConsoleTask):
  """Generates either a textual dependency tree or a graphviz digraph dot file for the dependency
  set of a target.
  """

  @staticmethod
  def _is_jvm(dep):
    return dep.is_jvm or dep.is_jvm_app

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

  def __init__(self, context):
    ConsoleTask.__init__(self, context)

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

  def console_output(self, targets):
    if len(self.context.target_roots) == 0:
      raise TaskError("One or more target addresses are required.")

    for target in self.context.target_roots:
      if all(self._is_jvm(t) for t in target.resolve() if t.is_concrete):
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

        if self._is_jvm(dep):
          for internal_dep in dep.internal_dependencies:
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

    return [dependency for t in target.resolve() for dependency in output_deps(t)]

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

        for dependency in dep.resolve():
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
