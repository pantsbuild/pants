# =============================================================================
# Copyright 2014 Twitter, Inc.
# -----------------------------------------------------------------------------
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
# =============================================================================

from twitter.pants.goal import Phase

from .console_task import ConsoleTask


class ListGoals(ConsoleTask):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    super(ListGoals, cls).setup_parser(option_group, args, mkflag)
    option_group.add_option(mkflag("all"),
                            dest="goal_list_all",
                            default=False,
                            action="store_true",
                            help="[%default] List all goals even if no description is available.")
    option_group.add_option(mkflag('graph'),
                            dest='goal_list_graph',
                            action='store_true',
                            help='[%default] Generate a graphviz graph of installed goals.')

  def console_output(self, targets):
    def report():
      yield 'Installed goals:'
      documented_rows = []
      undocumented = []
      max_width = 0
      for phase, _ in Phase.all():
        if phase.description:
          documented_rows.append((phase.name, phase.description))
          max_width = max(max_width, len(phase.name))
        elif self.context.options.goal_list_all:
          undocumented.append(phase.name)
      for name, description in documented_rows:
        yield '  %s: %s' % (name.rjust(max_width), description)
      if undocumented:
        yield ''
        yield 'Undocumented goals:'
        yield '  %s' % ' '.join(undocumented)

    def graph():
      def get_cluster_name(phase):
        return 'cluster_%s' % phase.name.replace('-', '_')

      def get_goal_name(phase, goal):
        name = '%s_%s' % (phase.name, goal.name)
        return name.replace('-', '_')

      phase_by_phasename = {}
      for phase, goals in Phase.all():
        phase_by_phasename[phase.name] = phase

      yield '\n'.join([
        'digraph G {',
        '  rankdir=LR;',
        '  graph [compound=true];',
        ])
      for phase, installed_goals in Phase.all():
        yield '\n'.join([
          '  subgraph %s {' % get_cluster_name(phase),
          '    node [style=filled];',
          '    color = blue;',
          '    label = "%s";' % phase.name,
        ])
        for installed_goal in installed_goals:
          yield '    %s [label="%s"];' % (get_goal_name(phase, installed_goal),
                                          installed_goal.name)
        yield '  }'

      edges = set()
      for phase, installed_goals in Phase.all():
        for installed_goal in installed_goals:
          for dependency in installed_goal.dependencies:
            tail_goal = phase_by_phasename.get(dependency.name).goals()[-1]
            edge = 'ltail=%s lhead=%s' % (get_cluster_name(phase),
                                          get_cluster_name(Phase.of(tail_goal)))
            if edge not in edges:
              yield '  %s -> %s [%s];' % (get_goal_name(phase, installed_goal),
                                          get_goal_name(Phase.of(tail_goal), tail_goal),
                                          edge)
            edges.add(edge)
      yield '}'

    return graph() if self.context.options.goal_list_graph else report()
