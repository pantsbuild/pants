# ==================================================================================================
# Copyright 2014 Twitter, Inc.
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

from twitter.pants.goal import Goal
from twitter.pants.goal.phase import Phase
from twitter.pants.tasks import Task
from twitter.pants.tasks.list_goals import ListGoals

from . import ConsoleTaskTest


class ListGoalsTest(ConsoleTaskTest):
  _INSTALLED_HEADER = 'Installed goals:'
  _UNDOCUMENTED_HEADER = 'Undocumented goals:'
  _LIST_GOALS_NAME = 'goals'
  _LIST_GOALS_DESC = 'List all documented goals.'
  _LLAMA_NAME = 'llama'
  _LLAMA_DESC = 'With such handsome fiber, no wonder everyone loves Llamas.'
  _ALPACA_NAME = 'alpaca'

  @classmethod
  def task_type(cls):
    return ListGoals

  class LlamaTask(Task):
    pass

  class AlpacaTask(Task):
    pass

  def test_list_goals(self):
    Phase.clear()
    self.assert_console_output(self._INSTALLED_HEADER)

    Goal(name=self._LIST_GOALS_NAME, action=ListGoals)\
      .install().with_description(self._LIST_GOALS_DESC)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  %s: %s' % (self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
    )

    Goal(name=self._LLAMA_NAME, action=ListGoalsTest.LlamaTask)\
      .install().with_description(self._LLAMA_DESC)
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  %s: %s' % (self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  %s: %s' % (self._LLAMA_NAME, self._LLAMA_DESC),
    )

    Goal(name=self._ALPACA_NAME, action=ListGoalsTest.AlpacaTask, dependencies=[self._LLAMA_NAME])\
      .install()
    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  %s: %s' % (self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  %s: %s' % (self._LLAMA_NAME, self._LLAMA_DESC),
    )

  def test_list_goals_all(self):
    Phase.clear()

    Goal(name=self._LIST_GOALS_NAME, action=ListGoals)\
      .install().with_description(self._LIST_GOALS_DESC)
    Goal(name=self._LLAMA_NAME, action=ListGoalsTest.LlamaTask)\
      .install().with_description(self._LLAMA_DESC)
    Goal(name=self._ALPACA_NAME, action=ListGoalsTest.AlpacaTask, dependencies=[self._LLAMA_NAME])\
      .install()

    self.assert_console_output(
      self._INSTALLED_HEADER,
      '  %s: %s' % (self._LIST_GOALS_NAME, self._LIST_GOALS_DESC),
      '  %s: %s' % (self._LLAMA_NAME, self._LLAMA_DESC),
      '',
      self._UNDOCUMENTED_HEADER,
      '  %s' % self._ALPACA_NAME,
      args=['--test-all'],
    )

  def test_list_goals_graph(self):
    Phase.clear()

    Goal(name=self._LIST_GOALS_NAME, action=ListGoals)\
      .install().with_description(self._LIST_GOALS_DESC)
    Goal(name=self._LLAMA_NAME, action=ListGoalsTest.LlamaTask)\
      .install().with_description(self._LLAMA_DESC)
    Goal(name=self._ALPACA_NAME, action=ListGoalsTest.AlpacaTask, dependencies=[self._LLAMA_NAME])\
      .install()

    self.assert_console_output(
      'digraph G {\n  rankdir=LR;\n  graph [compound=true];',
      '  subgraph cluster_goals {\n    node [style=filled];\n    color = blue;\n    label = "goals";',
      '    goals_goals [label="goals"];',
      '  }',
      '  subgraph cluster_llama {\n    node [style=filled];\n    color = blue;\n    label = "llama";',
      '    llama_llama [label="llama"];',
      '  }',
      '  subgraph cluster_alpaca {\n    node [style=filled];\n    color = blue;\n    label = "alpaca";',
      '    alpaca_alpaca [label="alpaca"];',
      '  }',
      '  alpaca_alpaca -> llama_llama [ltail=cluster_alpaca lhead=cluster_llama];',
      '}',
      args=['--test-graph'],
    )
