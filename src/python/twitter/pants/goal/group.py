
from collections import defaultdict

from twitter.common.collections import OrderedDict, OrderedSet
from twitter.pants import is_internal
from twitter.pants.goal.workunit import WorkUnit
from twitter.pants.targets import InternalTarget
from twitter.pants.tasks import TaskError


class Group(object):
  @staticmethod
  def _get_exclusives_product(context):
    return context.products.get_data('exclusives_groups')

  @staticmethod
  def execute(phase, tasks_by_goal, context, executed):
    """Executes the named phase against the current context tracking goal executions in executed."""

    def execute_task(name, task, targets):
      """Execute and time a single goal that has had all of its dependencies satisfied."""
      # We want the key for this group; we can find it using any representative member.
      # This first one is easy.
      try:
        # TODO (Senthil Kumaran):
        # Possible refactoring of the Task Execution Logic (AWESOME-1019)
        if getattr(context.options, 'explain', None):
          context.log.debug("Skipping execution of %s in explain mode" % name)
        else:
          task.execute(targets)
      finally:
        if phase not in executed:
          executed[phase] = OrderedDict()

    tasks_by_goalname = dict((goal.name, task.__class__.__name__)
                             for goal, task in tasks_by_goal.items())

    def expand_goal(goal):
      if len(goal) == 2: # goal is (group, goal)
        group_name, goal_name = goal
        task_name = tasks_by_goalname[goal_name]
        return "%s:%s->%s" % (group_name, goal_name, task_name)
      else:
        task_name = tasks_by_goalname[goal]
        return "%s->%s" % (goal, task_name)

    if phase not in executed:
      # Note the locking strategy: We lock the first time we need to, and hold the lock until
      # we're done, even if some of our deps don't themselves need to be serialized. This is
      # because we may implicitly rely on pristine state from an earlier phase.
      locked_by_me = False

      if context.is_unlocked() and phase.serialize():
        context.acquire_lock()
        locked_by_me = True
      # Satisfy dependencies first
      goals = phase.goals()
      if not goals:
        raise TaskError('No goals installed for phase %s' % phase)

      for goal in goals:
        for dependency in goal.dependencies:
          Group.execute(dependency, tasks_by_goal, context, executed)

      runqueue = []
      goals_by_group = {}
      for goal in goals:
        if goal.group:
          group_name = goal.group.name
          if group_name not in goals_by_group:
            group_goals = [goal]
            runqueue.append((group_name, group_goals))
            goals_by_group[group_name] = group_goals
          else:
            goals_by_group[group_name].append(goal)
        else:
          runqueue.append((None, [goal]))

      with context.new_workunit(name=phase.name, labels=[WorkUnit.PHASE]):
        # OrderedSet takes care of not repeating chunked task execution mentions
        execution_phases = defaultdict(OrderedSet)

        # Note that we don't explicitly set the outcome at the phase level. We just take
        # the outcomes that propagate up from the goal workunits.
        for group_name, goals in runqueue:
          if not group_name:
            goal = goals[0]
            execution_phases[phase].add(goal.name)
            with context.new_workunit(name=goal.name, labels=[WorkUnit.GOAL]):
              execute_task(goal.name, tasks_by_goal[goal], context.targets())
          else:
            with context.new_workunit(name=group_name, labels=[WorkUnit.GROUP]):
              for chunk in Group._create_chunks(context, goals):
                for goal in goals:
                  goal_chunk = filter(goal.group.predicate, chunk)
                  if len(goal_chunk) > 0:
                    execution_phases[phase].add((group_name, goal.name))
                    with context.new_workunit(name=goal.name, labels=[WorkUnit.GOAL]):
                      execute_task(goal.name, tasks_by_goal[goal], goal_chunk)

      if getattr(context.options, 'explain', None):
        for phase, goals in execution_phases.items():
          goal_to_task = ", ".join(expand_goal(goal) for goal in goals)
          print("%s [%s]" % (phase, goal_to_task))

      # Can't put this in a finally block because some tasks fork, and the forked processes would
      # execute this block as well.
      if locked_by_me:
        context.release_lock()

  @staticmethod
  def _create_chunks(context, goals):

    def discriminator(target):
      for i, goal in enumerate(goals):
        if goal.group.predicate(target):
          return i
      return 'other'

    # First, divide the set of all targets to be built into compatible chunks, based
    # on their declared exclusives. Then, for each chunk of compatible exclusives, do
    # further subchunking. At the end, we'll have a list of chunks to be built,
    # which will go through the chunks of each exclusives-compatible group separately.

    # TODO(markcc); chunks with incompatible exclusives require separate ivy resolves.
    # Either interleave the ivy task in this group so that it runs once for each batch of
    # chunks with compatible exclusives, or make the compilation tasks do their own ivy resolves
    # for each batch of targets they're asked to compile.

    exclusives = Group._get_exclusives_product(context)

    sorted_excl_group_keys = exclusives.get_ordered_group_keys()
    all_chunks = []

    for excl_group_key in sorted_excl_group_keys:
      # TODO(John Sirois): coalescing should be made available in another spot, InternalTarget is jvm
      # specific, and all we care is that the Targets have dependencies defined

      chunk_targets = exclusives.get_targets_for_group_key(excl_group_key)
      # need to extract the targets for this chunk that are internal.
      ## TODO(markcc): right here, we're using "context.targets", which doesn't respect any of the
      ## exclusives rubbish going on around here.
      #coalesced = InternalTarget.coalesce_targets(context.targets(is_internal), discriminator)
      coalesced = InternalTarget.coalesce_targets(filter(is_internal, chunk_targets), discriminator)
      coalesced = list(reversed(coalesced))

      def not_internal(target):
        return not is_internal(target)
      # got targets that aren't internal.
      #rest = OrderedSet(context.targets(not_internal))
      rest = OrderedSet(filter(not_internal, chunk_targets))


      chunks = [rest] if rest else []
      flavor = None
      chunk_start = 0
      for i, target in enumerate(coalesced):
        target_flavor = discriminator(target)
        if target_flavor != flavor and i > chunk_start:
          chunks.append(OrderedSet(coalesced[chunk_start:i]))
          chunk_start = i
        flavor = target_flavor
      if chunk_start < len(coalesced):
        chunks.append(OrderedSet(coalesced[chunk_start:]))
      all_chunks += chunks

    context.log.debug('::: created chunks(%d)' % len(all_chunks))
    for i, chunk in enumerate(all_chunks):
      flavor = discriminator(iter(chunk).next())
      context.log.debug('  chunk(%d) [flavor=%s]:\n\t%s' %
                        (i, flavor, '\n\t'.join(sorted(map(str, chunk)))))

    return all_chunks

  def __init__(self, name, predicate):
    self.name = name
    self.predicate = predicate
    self.exclusives = None

  def __repr__(self):
    return "Group(%s,%s)" % (self.name, self.predicate.__name__)
