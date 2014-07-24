# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import functools
import inspect
from optparse import OptionGroup

from pants.goal.error import GoalError
from pants.goal.phase import Phase
from pants.backend.core.tasks.task import Task


class Mkflag(object):
  """A factory for namespaced flags."""

  def __init__(self, *namespace):
    """Creates a new Mkflag that will use the given namespace to prefix the flags it creates.

    namespace: a sequence of names forming the namespace
    """
    self._namespace = namespace

  @property
  def namespace(self):
    return list(self._namespace)

  def __call__(self, name, negate=False):
    """Creates a prefixed flag with an optional negated prefix.

    name: The simple flag name to be prefixed.
    negate: True to prefix the flag with '--no-'.
    """
    return '--{negate}{namespace}-{name}'.format(negate='no-' if negate else '',
                                                 namespace='-'.join(self._namespace),
                                                 name=name)

  def set_bool(self, option, opt_str, _, parser):
    """An Option callback to parse bool flags that recognizes the --no- negation prefix."""
    setattr(parser.values, option.dest, not opt_str.startswith("--no"))


class Goal(object):
  def __init__(self, name, action, dependencies=None, serialize=True):
    """
    :param name: the name of the goal.
    :param action: the goal action object to invoke this goal.
    :param dependencies: the names of other goals which must be achieved before invoking this goal.
    :param serialize: a flag indicating whether or not the action to achieve this goal requires
      the global lock. If true, the action will block until it can acquire the lock.
    """
    self.serialize = serialize
    self.name = name
    self.dependencies = [Phase(d) for d in dependencies] if dependencies else []

    if isinstance(type(action), type) and issubclass(action, Task):
      self._task = action
    else:
      args, varargs, keywords, defaults = inspect.getargspec(action)
      if varargs or keywords or defaults:
        raise GoalError('Invalid action supplied, cannot accept varargs, keywords or defaults')
      if len(args) > 1:
        raise GoalError('Invalid action supplied, must accept either no args or else a single '
                        'Context object')

      class FuncTask(Task):
        def __init__(self, context, workdir):
          super(FuncTask, self).__init__(context, workdir)

          if not args:
            self.action = action
          elif len(args) == 1:
            self.action = functools.partial(action, self.context)
          else:
            raise AssertionError('Unexpected fallthrough')

        def execute(self):
          self.action()

      self._task = FuncTask

  def __repr__(self):
    return "Goal(%s; %s)" % (self.name, ','.join(map(str, self.dependencies)))

  @property
  def task_type(self):
    return self._task

  def _namespace_for_parser(self, phase):
    phase_leader = phase.goals() == [self] or self.name == phase.name
    return [self.name] if phase_leader else [phase.name, self.name]

  def title_for_option_group(self, phase):
    return ':'.join(self._namespace_for_parser(phase))

  def setup_parser(self, phase, parser, args):
    """Allows a task to add its command line args to the global specification."""
    namespace = self._namespace_for_parser(phase)
    mkflag = Mkflag(*namespace)
    option_group = OptionGroup(parser, title=':'.join(namespace))
    self.task_setup_parser(option_group, args, mkflag)
    if option_group.option_list:
      parser.add_option_group(option_group)

  def task_setup_parser(self, option_group, args, mkflag):
    """Allows a task to setup a parser.
    Override this method if you want to initialize the task with more goal data."""
    self._task.setup_parser(option_group, args, mkflag)

  def install(self, phase=None, first=False, replace=False, before=None, after=None):
    """Install this goal in the specified phase (or a new phase with the same name as this Goal).

    The placement of the goal in the execution list of the phase defaults to the end but can be
    influence by specifying exactly one of the following arguments:

    :param first: Places this goal 1st in the phase's execution list
    :param replace: Replaces any existing goals in the phase with this goal
    :param before: Places this goal before the named goal in the phase's execution list
    :param after: Places this goal after the named goal in the phase's execution list
    """
    phase = Phase(phase or self.name)
    phase.install(self, first, replace, before, after)
    return phase
