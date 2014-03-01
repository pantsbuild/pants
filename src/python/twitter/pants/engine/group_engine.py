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

from collections import defaultdict, namedtuple

from twitter.common.collections import OrderedDict, OrderedSet
from twitter.pants.base.workunit import WorkUnit

from twitter.pants.goal import Goal
from twitter.pants.targets.internal import InternalTarget
from twitter.pants.tasks import TaskError
from twitter.pants.tasks.check_exclusives import ExclusivesMapping

from .engine import Engine


class GroupMember(namedtuple('GroupMember', ['group', 'name', 'predicate'])):
  """Represents a member of a goal group."""

  @classmethod
  def from_goal(cls, goal):
    """Creates a ``GroupMember`` from goal metadata."""
    if not isinstance(goal, Goal):
      raise ValueError('The given goal must be a ``Goal`` object, given %s' % goal)
    if not goal.group:
      raise ValueError('Can only form a GroupMember from goals with a group defined, goal %s '
                       'has no group' % goal.name)
    return cls(goal.group.name, goal.name, goal.group.predicate)


class GroupIterator(object):
  """Iterates the goals in a group over the chunks they own,"""

  def __init__(self, targets, group_members):
    """Creates an iterator that yields tuples of ``(GroupMember, [chunk Targets])``.

    Chunks will be returned least dependant to most dependant such that a group member processing a
    chunk can be assured that any dependencies of the chunk have been processed already.

    :param list targets: The universe of targets to divide up amongst group members.
    :param list group_members: A list of group members that forms the group to iterate.
    """
    # TODO(John Sirois): These validations should be happening sooner in the goal registration
    # process.
    assert len(map(lambda m: m.group, group_members)) != 1, 'Expected a single group'
    assert len(map(lambda m: m.name, group_members)) == len(group_members), (
      'Expected group members with unique names')

    self._targets = targets
    self._group_members = group_members

  def __iter__(self):
    for chunk in self._create_chunks():
      for group_member in self._group_members:
        member_chunk = filter(group_member.predicate, chunk)
        if len(member_chunk) > 0:
          yield group_member, member_chunk

  def _create_chunks(self):
    def discriminator(tgt):
      for group_member in self._group_members:
        if group_member.predicate(tgt):
          return group_member.name
      return None

    # TODO(John Sirois): coalescing should be made available in another spot, InternalTarget is jvm
    # specific, and all we care is that the Targets have dependencies defined
    coalesced = InternalTarget.coalesce_targets(self._targets, discriminator)
    coalesced = list(reversed(coalesced))

    chunks = []
    flavor = None
    chunk_start = 0
    for chunk_num, target in enumerate(coalesced):
      target_flavor = discriminator(target)
      if target_flavor != flavor and chunk_num > chunk_start:
        chunks.append(OrderedSet(coalesced[chunk_start:chunk_num]))
        chunk_start = chunk_num
      flavor = target_flavor
    if chunk_start < len(coalesced):
      chunks.append(OrderedSet(coalesced[chunk_start:]))
    return chunks


class ExclusivesIterator(object):
  """Iterates over groups of compatible targets."""

  @classmethod
  def from_context(cls, context):
    exclusives = context.products.get_data('exclusives_groups')
    return cls(exclusives)

  def __init__(self, exclusives_mapping):
    """Creates an iterator that yields lists of compatible targets.``.

    Chunks will be returned in least exclusive to most exclusive order.

    :param exclusives_mapping: An ``ExclusivesMapping`` that contains the exclusive chunked targets
      to iterate.
    """
    if not isinstance(exclusives_mapping, ExclusivesMapping):
      raise ValueError('An ExclusivesMapping is required, given %s of type %s'
                       % (exclusives_mapping, type(exclusives_mapping)))
    self._exclusives_mapping = exclusives_mapping

  def __iter__(self):
    sorted_excl_group_keys = self._exclusives_mapping.get_ordered_group_keys()
    for excl_group_key in sorted_excl_group_keys:
      yield self._exclusives_mapping.get_targets_for_group_key(excl_group_key)


class GroupEngine(Engine):
  """The classical phase engine that has direct knowledge of groups and the bang algorithm.

  For grouped goals this engine attempts to make as few passes as possible through the target groups
  found.
  """

  class PhaseExecutor(object):
    def __init__(self, context, phase, tasks_by_goal):
      self._context = context
      self._phase = phase
      self._tasks_by_goal = tasks_by_goal

    @property
    def phase(self):
      return self._phase

    def attempt(self, timer, explain):
      """Executes the named phase against the current context tracking goal executions in executed.
      """
      def acquire_lock_if_needed(goal):
        """If the goal about to be executed requires the lock, then acquire it. If not,
        then make sure it's released.
        """
        if goal.serialize:
          self._context.acquire_lock()
        else:
          self._context.release_lock()

      def execute_task(goal, task, targets):
        """Execute and time a single goal that has had all of its dependencies satisfied."""
        with timer.timed(goal):
          # TODO (Senthil Kumaran):
          # Possible refactoring of the Task Execution Logic (AWESOME-1019)
          if explain:
            self._context.log.debug("Skipping execution of %s in explain mode" % goal.name)
          else:
            task.execute(targets)

      goals = self._phase.goals()
      if not goals:
        raise TaskError('No goals installed for phase %s' % self._phase)

      run_queue = []
      goals_by_group = {}
      for goal in goals:
        if goal.group:
          group_name = goal.group.name
          if group_name not in goals_by_group:
            group_goals = [goal]
            run_queue.append((group_name, group_goals))
            goals_by_group[group_name] = group_goals
          else:
            goals_by_group[group_name].append(goal)
        else:
          run_queue.append((None, [goal]))

      with self._context.new_workunit(name=self._phase.name, labels=[WorkUnit.PHASE]):
        # OrderedSet takes care of not repeating chunked task execution mentions
        execution_phases = defaultdict(OrderedSet)

        for group_name, goals in run_queue:
          if not group_name:
            goal = goals[0]
            acquire_lock_if_needed(goal)
            execution_phases[self._phase].add(goal.name)
            with self._context.new_workunit(name=goal.name, labels=[WorkUnit.GOAL]):
              execute_task(goal, self._tasks_by_goal[goal], self._context.targets())
          else:
            with self._context.new_workunit(name=group_name, labels=[WorkUnit.GROUP]):
              goals_by_group_member = OrderedDict((GroupMember.from_goal(g), g) for g in goals)

              # First, divide the set of all targets to be built into compatible chunks, based
              # on their declared exclusives. Then, for each chunk of compatible exclusives, do
              # further sub-chunking. At the end, we'll have a list of chunks to be built,
              # which will go through the chunks of each exclusives-compatible group separately.

              # TODO(markcc); chunks with incompatible exclusives require separate ivy resolves.
              # Either interleave the ivy task in this group so that it runs once for each batch of
              # chunks with compatible exclusives, or make the compilation tasks do their own ivy
              # resolves for each batch of targets they're asked to compile.

              goal_chunks = []

              # We won't have exclusives calculated if stopping short for example during an explain.
              if explain:
                exclusive_chunks = [self._context.targets()]
              else:
                exclusive_chunks = ExclusivesIterator.from_context(self._context)

              for exclusive_chunk in exclusive_chunks:
                group_chunks = GroupIterator(filter(lambda t: t.is_concrete, exclusive_chunk),
                                             goals_by_group_member.keys())
                goal_chunks.extend(group_chunks)

              self._context.log.debug('::: created chunks(%d)' % len(goal_chunks))
              for i, (group_member, goal_chunk) in enumerate(goal_chunks):
                self._context.log.debug('  chunk(%d) [flavor=%s]:\n\t%s' % (
                    i, group_member.name, '\n\t'.join(sorted(map(str, goal_chunk)))))

              for group_member, goal_chunk in goal_chunks:
                goal = goals_by_group_member[group_member]
                acquire_lock_if_needed(goal)
                execution_phases[self._phase].add((group_name, goal.name))
                with self._context.new_workunit(name=goal.name, labels=[WorkUnit.GOAL]):
                  execute_task(goal, self._tasks_by_goal[goal], goal_chunk)

        if explain:
          tasks_by_goalname = dict((goal.name, task.__class__.__name__)
                                   for goal, task in self._tasks_by_goal.items())

          def expand_goal(goal):
            if len(goal) == 2:  # goal is (group, goal)
              group_name, goal_name = goal
              task_name = tasks_by_goalname[goal_name]
              return "%s:%s->%s" % (group_name, goal_name, task_name)
            else:
              task_name = tasks_by_goalname[goal]
              return "%s->%s" % (goal, task_name)

          for phase, goals in execution_phases.items():
            goal_to_task = ", ".join(expand_goal(goal) for goal in goals)
            print("%s [%s]" % (phase, goal_to_task))

  @classmethod
  def _prepare(cls, context, phases):
    tasks_by_goal = {}

    # We loop here because a prepared goal may introduce new BUILDs and thereby new Goals/Phases.
    # We need to prepare these in a subsequent loop until the set of phases and goals quiesces.
    prepared_goals = set()
    round_num = 0
    while True:
      phases = list(cls.execution_order(phases))
      if prepared_goals == reduce(lambda goals, p: goals | set(p.goals()), phases, set()):
        break

      round_num += 1
      context.log.debug('Preparing goals in round %d' % round_num)
      # Prepare tasks roots to leaves and allow for downstream tasks requiring products from
      # upstream tasks they depend upon.
      for phase in reversed(phases):
        for goal in reversed(phase.goals()):
          if goal not in prepared_goals:
            context.log.debug('preparing: %s:%s' % (phase.name, goal.name))
            prepared_goals.add(goal)
            task = goal.task_type(context)
            tasks_by_goal[goal] = task

    return map(lambda p: cls.PhaseExecutor(context, p, tasks_by_goal), phases)

  def attempt(self, timer, context, phases):
    phase_executors = self._prepare(context, phases)

    execution_phases = ' -> '.join(map(str, map(lambda e: e.phase.name, phase_executors)))
    context.log.debug('Executing goals in phases %s' % execution_phases)

    explain = context.options.explain
    if explain:
      print("Phase Execution Order:\n\n%s\n" % execution_phases)
      print("Phase [Goal->Task] Order:\n")

    for phase_executor in phase_executors:
      phase_executor.attempt(timer, explain)
