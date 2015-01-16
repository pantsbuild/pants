# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.backend.core.tasks.reflect import (gen_goals_glopts_reference_data,
                                              gen_tasks_goals_reference_data)
from pants.goal.goal import Goal


class ListGoals(ConsoleTask):
  @classmethod
  def register_options(cls, register):
    super(ListGoals, cls).register_options(register)
    register('--graph', action='store_true',
             help='Generate a graphviz graph of installed goals.')
    register('--all-options', action='store_true',
             help='List options with goals. (For more readable, use ./pants goal foo -h)')
    register('--all', action='store_true',
             help='List all goals even if no description is available.')

  def console_output(self, targets):
    def report():
      yield 'Installed goals:'
      documented_rows = []
      undocumented = []
      max_width = 0
      for goal in Goal.all():
        if goal.description:
          documented_rows.append((goal.name, goal.description))
          max_width = max(max_width, len(goal.name))
        elif self.get_options().all:
          undocumented.append(goal.name)
      for name, description in documented_rows:
        yield '  %s: %s' % (name.rjust(max_width), description)
      if undocumented:
        yield ''
        yield 'Undocumented goals:'
        yield '  %s' % ' '.join(undocumented)

    def report_with_options():
      yield self.context.options.format_global_help()
      for goal in Goal.all():
        yield '\n{0}: {1}\n'.format(goal.name, goal.description or '')
        for scope in goal.known_scopes():
          yield self.context.options.format_help(scope)

    def graph():
      # TODO(John Sirois): re-work and re-enable: https://github.com/pantsbuild/pants/issues/918
      # def get_cluster_name(goal):
      #   return 'cluster_%s' % goal.name.replace('-', '_')
      #
      # def get_node_name(goal, task_name):
      #   name = '%s_%s' % (goal.name, task_name)
      #   return name.replace('-', '_')
      #
      # yield '\n'.join([
      #   'digraph G {',
      #   '  rankdir=LR;',
      #   '  graph [compound=true];',
      #   ])
      # for goal in Goal.all():
      #   yield '\n'.join([
      #     '  subgraph %s {' % get_cluster_name(goal),
      #     '    node [style=filled];',
      #     '    color = blue;',
      #     '    label = "%s";' % goal.name,
      #   ])
      #   for name in goal.ordered_task_names():
      #     yield '    %s [label="%s"];' % (get_node_name(goal, name), name)
      #   yield '  }'
      #
      # edges = set()
      # for goal in Goal.all():
      #   tail_task_name = goal.ordered_task_names()[-1]
      #   for dep in goal.dependencies:
      #     edge = 'ltail=%s lhead=%s' % (get_cluster_name(goal), get_cluster_name(dep))
      #     if edge not in edges:
      #       # We display edges between clusters (representing goals), but dot still requires
      #       # us to specify them between nodes (representing tasks) and then add ltail, lhead
      #       # annotations.  We connect the last task in the dependee to the first task in
      #       # the dependency, as this leads to the neatest-looking graph.
      #       yield '  %s -> %s [%s];' % (get_node_name(goal, tail_task_name),
      #                                   get_node_name(dep, dep.ordered_task_names()[0]), edge)
      #     edges.add(edge)
      # yield '}'
      yield 'Graph support is currently broken but will be resurrected pending engine rework'
      yield 'You can follow progress towards this milestone here:'
      yield '  https://github.com/pantsbuild/pants/milestones/engine%20rework'
      yield 'You can follow final fix-up of --graph here:'
      yield '  https://github.com/pantsbuild/pants/issues/918'

    if self.get_options().graph:
      return graph()
    elif self.get_options().all_options:
      return report_with_options()
    else:
      return report()
