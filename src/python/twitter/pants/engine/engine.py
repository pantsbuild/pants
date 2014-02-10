# ==================================================================================================
# Copyright 2013 Twitter, Inc.
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

import time

from abc import abstractmethod
from contextlib import contextmanager

from twitter.common.collections.ordereddict import OrderedDict
from twitter.common.lang import AbstractClass

from twitter.pants import TaskError
from twitter.pants.goal import GoalError, Phase


class Timer(object):
  """Provides timing support for goal execution."""

  @classmethod
  @contextmanager
  def begin(cls, timer=None):
    """Begins a new ``Timer`` and yields it in a with context.

    The timer will be finished if not already by the block yielded to.
    """
    t = Timer(timer)
    try:
      yield t
    finally:
      t.finish()

  def __init__(self, timer=None):
    """Creates a timer that uses time.time for timing intervals by default.

    :param timer:  A callable that returns the current time in fractional seconds.
    """
    self._now = timer or time.time
    if not(callable(self._now)):
      # TODO(John Sirois): `def jake(bob): pass` is also callable - we want a no-args callable -
      # create a better check.
      raise ValueError('Timer must be a callable object.')

    self._timings = OrderedDict()
    self._elapsed = None
    self._start = self._now()

  def finish(self):
    """Finishes this timer if not already finished.

    Calls to ``timed`` after this will raise a ValueError since the timing window is complete.
    """
    if self._elapsed is None:
      self._elapsed = self._now() - self._start

  @property
  def timings(self):
    """Returns the phase timings as an ordered mapping from the ``Phase`` objects executed to
    ordered mappings of the ``Goal`` objects executed in the phase to the list of timings
    corresponding to each execution of the goal.

    Note that the list of timings will be singleton for all goals except those participating in a
    ``Group``.  Grouped goals will have or more timings in the list corresponding to each chunk of
    targets the goal executed against when iterating the group.
    """
    return self._timings

  @property
  def elapsed(self):
    """Returns the total elapsed time in fractional seconds from the creation of this timer until
    it was ``finished``.
    """
    if self._elapsed is None:
      raise ValueError('Timer has not been finished yet.')
    return self._elapsed

  @contextmanager
  def timed(self, goal):
    """Records the time taken to execute the yielded block an records this timing against the given
    goal's total runtime.
    """
    if self._elapsed is not None:
      raise ValueError('This timer is already finished.')

    start = self._now()
    try:
      yield
    finally:
      self._record(goal, self._now() - start)

  def _record(self, goal, elapsed):
    phase = Phase.of(goal)

    phase_timings = self._timings.get(phase)
    if phase_timings is None:
      phase_timings = OrderedDict(())
      self._timings[phase] = phase_timings

    goal_timings = phase_timings.get(goal)
    if goal_timings is None:
      goal_timings = []
      phase_timings[goal] = goal_timings

    goal_timings.append(elapsed)

  def render_timing_report(self):
    """Renders this timer's timings into the classic pants timing report format."""
    report = ('Timing report\n'
              '=============\n')
    for phase, timings in self.timings.items():
      phase_time = None
      for goal, times in timings.items():
        if len(times) > 1:
          report += '[%(phase)s:%(goal)s(%(numsteps)d)] %(timings)s -> %(total).3fs\n' % {
            'phase': phase.name,
            'goal': goal.name,
            'numsteps': len(times),
            'timings': ','.join('%.3fs' % t for t in times),
            'total': sum(times)
          }
        else:
          report += '[%(phase)s:%(goal)s] %(total).3fs\n' % {
            'phase': phase.name,
            'goal': goal.name,
            'total': sum(times)
          }
        if not phase_time:
          phase_time = 0
        phase_time += sum(times)
      if len(timings) > 1:
        report += '[%(phase)s] total: %(total).3fs\n' % {
          'phase': phase.name,
          'total': phase_time
        }
    report += 'total: %.3fs' % self.elapsed
    return report


class Engine(AbstractClass):
  """An engine for running a pants command line."""

  @staticmethod
  def execution_order(phases):
    """Yields all phases needed to attempt the given phases in proper phase execution order."""

    # Its key that we process phase dependencies depth first to maintain initial phase ordering as
    # passed in when phase graphs are dependency disjoint.  A breadth first sort could mix next
    # order executions and violate the implied intent of the passed in phase ordering.

    processed = set()

    def order(_phases):
      for phase in _phases:
        if phase not in processed:
          processed.add(phase)
          for goal in phase.goals():
            for dep in order(goal.dependencies):
              yield dep
          yield phase

    for ordered in order(phases):
      yield ordered

  def __init__(self, print_timing=False):
    """Creates an engine that prints no timings by default.

    :param print_timing: ``True`` to print detailed timings at the end of the run.
    """
    self._print_timing = print_timing

  def execute(self, context, phases):
    """Executes the supplied phases and their dependencies against the given context.

    :param context: The pants run context.
    :param list phases: A list of ``Phase`` objects representing the command line goals explicitly
                        requested.
    :returns int: An exit code of 0 upon success and non-zero otherwise.
    """
    with Timer.begin() as timer:
      try:
        self.attempt(timer, context, phases)
        return 0
      except (TaskError, GoalError) as e:
        message = '%s' % e
        if message:
          print('\nFAILURE: %s\n' % e)
        else:
          print('\nFAILURE\n')
        return e.exit_code if isinstance(e, TaskError) else 1
      finally:
        timer.finish()
        if self._print_timing:
          print(timer.render_timing_report())

  @abstractmethod
  def attempt(self, timer, context, phases):
    """Given the target context and phases specified (command line goals), attempt to achieve all
    goals.

    :param timer: A ``Timer`` that should be used to record goal timings.
    :param context: The pants run context.
    :param list phases: A list of ``Phase`` objects representing the command line goals explicitly
                        requested.
    """
