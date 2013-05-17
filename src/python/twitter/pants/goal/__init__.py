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

__author__ = 'John Sirois'

import inspect
from optparse import OptionGroup

from twitter.pants.tasks import Task


class GoalError(Exception):
  """Raised to indicate a goal has failed."""


from twitter.pants.goal.phase import Phase


class Mkflag(object):
  """A factory for namespaced flags."""

  def __init__(self, namespace):
    """Creates a new Mkflag that will use the given namespace to prefix the flags it creates.

    namespace: Either a function accepting a separator string that returns a prefix string for the
               flag or else a fixed prefix string for all flags.
    """
    self._namespace = namespace if callable(namespace) else lambda sep: namespace

  def __call__(self, name, negate=False):
    """Creates a prefixed flag with an optional negated prefix.

    name: The simple flag name to be prefixed.
    negate: True to prefix the flag with '--no-'.
    """
    return '--%s%s-%s' % ('no-' if negate else '', self._namespace('-'), name)

  def set_bool(self, option, opt_str, _, parser):
    """An Option callback to parse bool flags that recognizes the --no- negation prefix."""
    setattr(parser.values, option.dest, not opt_str.startswith("--no"))


class Goal(object):
  def __init__(self, name, action, group=None, dependencies=None, serialize=True):
    """Parameters:
       name: the name of the goal.
       action: the goal action object to invoke this goal.
       dependencies: the names of other goals which must be achieved
          before invoking this goal.
       serialize: a flag indicating whether or not the action to achieve
          this goal requires the global lock. If true, the action will
          block until it can acquire the lock.
    """
    self.serialize = serialize
    self.name = name
    self.group = group
    self.dependencies = [Phase(d) for d in dependencies] if dependencies else []

    if type(action) == type and issubclass(action, Task):
      self._task = action
    else:
      args, varargs, keywords, defaults = inspect.getargspec(action)
      if varargs or keywords or defaults:
        raise GoalError('Invalid action supplied, cannot accept varargs, keywords or defaults')
      if len(args) > 2:
        raise GoalError('Invalid action supplied, must accept 0, 1, or 2 args')

      class FuncTask(Task):
        def __init__(self, context):
          Task.__init__(self, context)

          if not args:
            self.action = lambda targets: action()
          elif len(args) == 1:
            self.action = lambda targets: action(self.context)
          elif len(args) == 2:
            self.action = lambda targets: action(self.context, targets)
          else:
            raise AssertionError('Unexpected fallthrough')

        def execute(self, targets):
          self.action(targets)

      self._task = FuncTask

  def __repr__(self):
    return "Goal(%s-%s; %s)" % (self.name, self.group, ','.join(map(str, self.dependencies)))

  @property
  def task_type(self):
    return self._task

  def setup_parser(self, phase, parser, args):
    """Allows a task to add its command line args to the global sepcification."""
    def namespace(sep):
      phase_leader = phase.goals() == [self] or self.name == phase.name
      return self.name if phase_leader else '%s%s%s' % (phase.name, sep, self.name)
    mkflag = Mkflag(namespace)

    group = OptionGroup(parser, title = namespace(':'))
    self._task.setup_parser(group, args, mkflag)
    if group.option_list:
      parser.add_option_group(group)

  def prepare(self, context):
    """Prepares a Task that can be executed to achieve this goal."""
    return self._task(context)

  def install(self, phase=None, first=False, replace=False, before=None, after=None):
    """
      Installs this goal in the specified phase (or a new phase with the same name as this Goal).

      The placement of the goal in the execution list of the phase defaults to the end but can be
      influence by specifying exactly one of the following arguments:

      first: Places this goal 1st in the phase's execution list
      replace: Replaces any existing goals in the phase with this goal
      before: Places this goal before the named goal in the phase's execution list
      after: Places this goal after the named goal in the phase's execution list
    """
    phase = Phase(phase or self.name)
    phase.install(self, first, replace, before, after)
    return phase

from twitter.pants.goal.context import Context
from twitter.pants.goal.group import Group
from twitter.pants.goal.run_tracker import RunTracker
from twitter.pants.goal.default_reporting import default_report

__all__ = (
  'Context',
  'Goal',
  'GoalError',
  'Group',
  'Phase',
  'RunTracker',
  'default_report'
)
