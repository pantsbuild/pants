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


class Goal(object):
  def __init__(self, name, action, group=None, dependencies=None):
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

  def setup_parser(self, phase, parser, args):
    """Allows a task to add its command line args to the global sepcification."""
    def namespace(sep):
      phase_leader = phase.goals() == [self] or self.name == phase.name
      return self.name if phase_leader else '%s%s%s' % (phase.name, sep, self.name)

    group = OptionGroup(parser, title = namespace(':'))

    def mkflag(arg_name, negate=False):
      return '--%s%s-%s' % ('no-' if negate else '', namespace('-'), arg_name)

    def set_bool(option, opt_str, value, parser):
      setattr(parser.values, option.dest, not opt_str.startswith("--no"))
    mkflag.set_bool = set_bool

    self._task.setup_parser(group, args, mkflag)

    if group.option_list:
      parser.add_option_group(group)

  def prepare(self, context):
    """Prepares a Task that can be executed to achieve this goal."""
    return self._task(context)

  def install(self, phase=None, first=False, replace=False, before=None):
    """
      Installs this goal in the specified phase (or a new phase with the same name as this Goal),
      appending to any pre-existing goals unless first=True in which case it is installed as the
      first goal in the phase.  If replace=True then this goal replaces all others for the phase.
      The phase this goal is installed in is returned. If before is not None, installs this goal
      right before the goal marked by before.
    """
    phase = Phase(phase or self.name)
    phase.install(self, first, replace, before)
    return phase

from twitter.pants.goal.context import Context
from twitter.pants.goal.group import Group

__all__ = (
  'Context',
  'Goal',
  'GoalError',
  'Group',
  'Phase'
)
