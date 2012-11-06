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
  renames = dict()

  def rename(cls, phase, name):
    """
      Renames the given phase and ensures all future requests for the old name are mapped to the
      given phase instance.
    """
    cls.phases.pop(phase.name)
    cls.renames[phase.name] = name
    phase.name = name
    cls.phases[name] = phase

  def __call__(cls, name):
    name = cls.renames.get(name, name)
    if name not in cls.phases:
      cls.phases[name] = super(SingletonPhases, cls).__call__(name)
    return cls.phases[name]

# Python 2.x + 3.x wankery
PhaseBase = SingletonPhases('PhaseBase', (object,), {})

class Phase(PhaseBase):
  _goals_by_phase = defaultdict(list)
  _phase_by_goal = dict()

  @staticmethod
  def of(goal):
    return Phase._phase_by_goal[goal]

  @staticmethod
  def goals_of_type(goal_class):
    """Returns all installed goals of the specified type."""
    return [goal for goal in Phase._phase_by_goal.keys() if isinstance(goal, goal_class)]

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
    executed = OrderedDict()

    # I'd rather do this in a finally block below, but some goals os.fork and each of these cause
    # finally to run, printing goal timings multiple times instead of once at the end.
    def emit_timings():
      if timer:
        for phase, timings in executed.items():
          for goal, times in timings.items():
            timer.log('%s:%s' % (phase, goal), times)

    try:
      # Prepare tasks roots to leaves and allow for goals introducing new goals in existing phases.
      tasks_by_goal = {}
      expanded = OrderedSet()
      prepared = set()
      round = 0
      while True:
        goals = list(Phase.execution_order(phases))
        if set(goals) == prepared:
          break
        else:
          round += 1
          context.log.debug('Preparing goals in round %d' % round)
          for goal in reversed(goals):
            if goal not in prepared:
              phase = Phase.of(goal)
              expanded.add(phase)
              context.log.debug('preparing: %s:%s' % (phase, goal.name))
              prepared.add(goal)
              task = goal.prepare(context)
              tasks_by_goal[goal] = task

      # Execute phases leaves to roots
      context.log.debug(
        'Executing goals in phases %s' % ' -> '.join(map(str, reversed(expanded)))
      )
      for phase in phases:
        Group.execute(phase, tasks_by_goal, context, executed, timer=timer)

      emit_timings()
      return 0
    except (TaskError, GoalError) as e:
      message = '%s' % e
      if message:
        print('\nFAILURE: %s\n' % e)
      else:
        print('\nFAILURE\n')
      emit_timings()
      return 1

  @staticmethod
  def execute(context, *names):
    parser = OptionParser()
    phases = [Phase(name) for name in names]
    Phase.setup_parser(parser, [], phases)
    options, _ = parser.parse_args([])
    context = Context(context.config, options, context.target_roots, log=context.log)
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
    return self

  def install(self, goal, first=False, replace=False, before=None, after=None):
    """
      Installs the given goal in this phase.  The placement of the goal in this phases' execution
      list defaults to the end but its position can be influence by specifying exactly one of the
      following arguments:

      first: Places the goal 1st in the execution list
      replace: Removes all existing goals in this phase and installs this goal
      before: Places the goal before the named goal in the execution list
      after: Places the goal after the named goal in the execution list
    """

    if (first or replace or before or after) and not (first ^ replace ^ bool(before) ^ bool(after)):
      raise GoalError('Can only specify one of first, replace, before or after')

    Phase._phase_by_goal[goal] = self

    g = self.goals()
    if replace:
      del g[:]
    g_names = map(lambda goal: goal.name, g)
    if first:
      g.insert(0, goal)
    elif before in g_names:
      g.insert(g_names.index(before), goal)
    elif after in g_names:
      g.insert(g_names.index(after)+1, goal)
    else:
      g.append(goal)
    return self

  def rename(self, name):
    """Renames this goal."""
    PhaseBase.rename(self, name)
    return self

  def remove(self, name):
    """Removes the named goal from this phase's list of goals to attempt."""
    goals = self.goals()
    for goal in goals:
      if goal.name == name:
        goals.remove(goal)
        return self
    raise GoalError('Goal %s does not exist in this phase, members are: %s' % (name, goals))

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
