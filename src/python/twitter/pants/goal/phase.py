from __future__ import print_function

from collections import defaultdict
from optparse import OptionParser

from twitter.common.collections import OrderedDict, OrderedSet
from twitter.pants.goal import GoalError
from twitter.pants.goal.group import Group
from twitter.pants.goal.context import Context
from twitter.pants.tasks import TaskError


class SingletonPhases(type):
  phases = dict()
  def __call__(cls, name):
    if name not in cls.phases:
      cls.phases[name] = super(SingletonPhases, cls).__call__(name)
    return cls.phases[name]

# Python 2.x + 3.x wankery
PhaseBase = SingletonPhases('PhaseBase', (object,), {})

class Phase(PhaseBase):
  _goals_by_phase = defaultdict(list)

  @staticmethod
  def setup_parser(parser, args, phases):
    def do_setup_parser(phase, setup):
      for goal in phase.goals():
        if goal not in setup:
          setup.add(goal)
          for dep in goal.dependencies:
            do_setup_parser(dep, setup)
          goal.setup_parser(phase, parser, args)

    setup = set()
    for phase in phases:
      do_setup_parser(phase, setup)

  @staticmethod
  def execution_order(phases):
    """
      Yields goals in execution order for the given phases.  Does not account for goals run
      multiple times due to grouping.
    """
    dependencies_by_goal = OrderedDict()
    def populate_dependencies(phases):
      for phase in phases:
        for goal in phase.goals():
          if goal not in dependencies_by_goal:
            populate_dependencies(goal.dependencies)
            deps = OrderedSet()
            for phasedep in goal.dependencies:
              deps.update(phasedep.goals())
            dependencies_by_goal[goal] = deps
    populate_dependencies(phases)

    while dependencies_by_goal:
      for goal, deps in dependencies_by_goal.items():
        if not deps:
          dependencies_by_goal.pop(goal)
          for _, deps in dependencies_by_goal.items():
            if goal in deps:
              deps.discard(goal)
          yield goal

  @staticmethod
  def attempt(context, phases, timer=None):
    """
      Attempts to reach the goals for the supplied phases, optionally recording phase timings and
      then logging then when all specified phases have completed.
    """

    start = timer.now() if timer else None
    executed = OrderedDict()

    # I'd rather do this in a finally block below, but some goals os.fork and each of these cause
    # finally to run, printing goal timings multiple times instead of once at the end.
    def print_timings():
      if timer:
        timer.log('Timing report')
        timer.log('=============')
        for phase, timings in executed.items():
          phase_time = None
          for goal, times in timings.items():
            if len(times) > 1:
              timer.log('[%(phase)s:%(goal)s(%(numsteps)d)] %(timings)s -> %(total).3fs' % {
                'phase': phase,
                'goal': goal,
                'numsteps': len(times),
                'timings': ','.join('%.3fs' % time for time in times),
                'total': sum(times)
              })
            else:
              timer.log('[%(phase)s:%(goal)s] %(total).3fs' % {
                'phase': phase,
                'goal': goal,
                'total': sum(times)
              })
            if not phase_time:
              phase_time = 0
            phase_time += sum(times)
          if len(timings) > 1:
            timer.log('[%(phase)s] total: %(total).3fs' % {
              'phase': phase,
              'total': phase_time
            })
        elapsed = timer.now() - start
        timer.log('total: %.3fs' % elapsed)

    try:
      # Prepare tasks roots to leaves
      tasks_by_goal = {}
      for goal in reversed(list(Phase.execution_order(phases))):
        task = goal.prepare(context)
        tasks_by_goal[goal] = task

      # Execute phases leaves to roots
      for phase in phases:
        Group.execute(phase, tasks_by_goal, context, executed, timer=timer)

      print_timings()
      return 0
    except (TaskError, GoalError) as e:
      message = '%s' % e
      if message:
        print('\nFAILURE: %s\n' % e)
      else:
        print('\nFAILURE\n')
      print_timings()
      return 1

  @staticmethod
  def execute(context, *names):
    parser = OptionParser()
    phases = [Phase(name) for name in names]
    Phase.setup_parser(parser, [], phases)
    options, _ = parser.parse_args([])
    context = Context(context.config, options, context.target_roots, context.log)
    return Phase.attempt(context, phases)

  @staticmethod
  def all():
    """Returns all registered goals as a sorted sequence of phase, goals tuples."""
    return sorted(Phase._goals_by_phase.items(), key=lambda pair: pair[0].name)

  def __init__(self, name):
    self.name = name
    self.description = None

  def with_description(self, description):
    self.description = description

  def install(self, goal, first=False, replace=False, before=None):
    g = self.goals()
    if replace:
      del g[:]
    g_names = map(lambda goal: goal.name, g)
    if first:
      g.insert(0, goal)
    elif before in g_names:
      g.insert(g_names.index(before), goal)
    else:
      g.append(goal)

  class UnsatisfiedDependencyError(GoalError):
    """Raised when an operation cannot be completed due to an unsatisfied goal dependency."""

  def uninstall(self):
    """
      Removes the named phase and all its attached goals.  Raises Phase.UnsatisfiedDependencyError
      if the removal cannot be completed due to a dependency.
    """
    for phase, goals in Phase._goals_by_phase.items():
      for goal in goals:
        for dependee_phase in goal.dependencies:
          if self is dependee_phase:
            raise Phase.UnsatisfiedDependencyError(
              '%s is depended on by %s:%s' % (self.name, phase.name, goal.name))
    del Phase._goals_by_phase[self]

  def goals(self):
    return Phase._goals_by_phase[self]

  def __repr__(self):
    return self.name
