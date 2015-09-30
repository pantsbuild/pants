# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from abc import abstractmethod, abstractproperty
from collections import defaultdict, deque
from contextlib import contextmanager

from pants.backend.core.tasks.task import Task, TaskBase
from pants.base.workunit import WorkUnit, WorkUnitLabel
from pants.build_graph.build_graph import invert_dependencies
from pants.goal.goal import Goal


class GroupMember(TaskBase):

  @classmethod
  def name(cls):
    """Returns a name for this group for display purposes.

    By default returns the GroupMember subtype's class name.
    """
    return cls.__name__

  @abstractmethod
  def select(self, target):
    """Return ``True`` to claim the target for processing.

    Group members are consulted in the order registered in their ``GroupTask`` and the 1st group
    member to select a target claims it.  Only that group member will be asked to prepare execution
    and later execute over a chunk containing the target.
    """

  def pre_execute(self):
    """Called before preparing chunks for execution

    Always called; even if no chunks are selected by this group member.
    """

  def prepare_execute(self, chunks):
    """Prepare to execute the group action across the given target chunks

    Only called if chunks have been selected by this group member.

    Chunks are guaranteed to be presented in least dependent to most dependent order and to contain
    only directly or indirectly invalidated targets.

    :param list chunks: A list of chunks, each chunk being a list of targets that should be
      processed together.
    """

  @abstractmethod
  def execute_chunk(self, targets):
    """Process the targets in this chunk.

    Only called if chunks have been selected by this group member.

    This chunk or targets' dependencies are guaranteed to have been processed in a prior
    ``execute_chunk`` round by some group member - possibly this one.

    :param list targets: A list of targets that should be processed together (ie: 1 chunk)
    """

  def finalize_execute(self, chunks):
    """Finalize execution of the group action across the given target chunks

    Only called if chunks have been selected by this group member.

    Chunks are guaranteed to be presented in least dependent to most dependent order and to contain
    only directly or indirectly invalidated targets.

    :param list chunks: A list of chunks, each chunk being a list of targets that should be
      processed together.
    """

  def post_execute(self):
    """Called when all invalid targets claimed by the group have been processed.

    Always called; even if no chunks are selected by this group member.
    """


class GroupIterator(object):
  """Iterates the goals in a group over the chunks they own."""

  @staticmethod
  def coalesce_targets(targets, discriminator):
    """Returns a list of Targets that `targets` depend on sorted from least dependent to most.

    The targets are grouped where possible by target type as categorized by the given discriminator.

    This algorithm was historically known as the "bang" algorithm from a time when it was
    optionally enabled by appending a '!' (bang) to the command line target.
    """

    # We want to sort targets topologically, grouping targets of the same type if possible.
    # Algorithm: BFS on the dependency graph with a separate queue per each type.
    # First, enqueue the least dependent targets (roots). Choose a type with a non-empty queue,
    # and process nodes from this queue until it's exhausted, then move on to the next non-empty
    # queue. "To process" means to add the node to the resulting list, and to increment
    # the number of "satisfied" dependencies for all its direct dependees. For every dependee
    # that has all its dependencies satisfied, enqueue it in the corresponding queue.
    # Since it's a directed acyclic graph, eventually all targets will be processed and added
    # to the resulting list.
    #
    # This linear-complexity algorithm replaces the worst-case-quadratic-complexity algorithm
    # that used DFS for topological sort, then trying to rearrange the targets in the resulting
    # list without breaking the sorting order, repeatedly computing full dependency closure
    # for the targets in the list.
    #
    # For benchmarking, "./pants compile" command was executed on a large target with about 1K nodes
    # in the dependency graph. The machine was 2013 MPB with SSD.
    # The quadratic implementation took on average about 18 seconds. The linear implementation
    # took on average about 1 second.

    roots, inverted_deps = invert_dependencies(targets)

    queues = defaultdict(deque)
    queues_total_size = 0

    # Enqueue roots.
    for root in roots:
      root_type = discriminator(root)
      queues[root_type].append(root)
      queues_total_size += 1

    sorted_targets = []
    satisfied_deps = defaultdict(int)
    current_type = None
    # Is there anything left to process?
    while queues_total_size > 0:
      # Choose a type with a non-empty queue.
      for potential_type in queues.keys():
        if queues[potential_type]:
          current_type = potential_type
          break
      # Process targets of this type while possible - they will form a single chunk.
      while queues[current_type]:
        target = queues[current_type].popleft()
        queues_total_size -= 1
        sorted_targets.append(target)

        # Let the dependees know that one more dependency is satisfied.
        if target in inverted_deps:
          for dependee in inverted_deps[target]:
            satisfied_deps[dependee] += 1
            # Does the dependee have all its dependencies satisfied now?
            if satisfied_deps[dependee] == len(dependee.dependencies):
              dependee_type = discriminator(dependee)
              queues[dependee_type].append(dependee)
              queues_total_size += 1

    # Remove targets that are not claimed by any member.
    sorted_targets = filter(discriminator, sorted_targets)

    return sorted_targets

  def __init__(self, targets, group_members):
    """Creates an iterator that yields tuples of ``(GroupMember, [chunk Targets])``.

    Chunks will be returned least dependent to most dependent such that a group member processing a
    chunk can be assured that any dependencies of the chunk have been processed already.

    :param list targets: The universe of targets to divide up amongst group members.
    :param list group_members: A list of group members that forms the group to iterate.
    """
    self._targets = targets
    self._group_members = group_members

  def __iter__(self):
    for group_member, chunk in self._create_chunks():
      yield group_member, chunk

  def _create_chunks(self):
    # memoized mapping from target to its type (i.e. member)
    target_to_member = dict()

    def discriminator(tgt):
      if tgt in target_to_member:
        return target_to_member[tgt]
      for member in self._group_members:
        if member.select(tgt):
          target_to_member[tgt] = member
          return member
      target_to_member[tgt] = None
      return None

    coalesced = self.coalesce_targets(self._targets, discriminator)

    chunks = []

    def add_chunk(member, chunk):
      if member is not None:
        chunks.append((member, chunk))

    group_member = None
    chunk_start = 0
    for chunk_num, target in enumerate(coalesced):
      target_group_member = discriminator(target)
      if target_group_member != group_member and chunk_num > chunk_start:
        add_chunk(group_member, coalesced[chunk_start:chunk_num])
        chunk_start = chunk_num
      group_member = target_group_member
    if chunk_start < len(coalesced):
      add_chunk(group_member, coalesced[chunk_start:])

    return chunks


class GroupTask(Task):
  """A task that coordinates group members who all produce a single product type.

  The canonical example is a group of different compilers targeting the same output format; for
  example: javac, groovyc, scalac and clojure aot all produce classfiles for the jvm and may depend
  on each others outputs for linkage.

  Since group members may depend on other group members outputs (a grouped task is only useful if
  they do!), a group task ensures that each member is executed in the proper order with the proper
  input targets such that its product dependencies are met.  Group members only need claim the
  targets they own in their `select` implementation and the group task will figure out the rest
  from the dependency relationships between the targets selected by the groups members.
  """

  _GROUPS = dict()

  @classmethod
  def named(cls, name, product_type, flag_namespace=None):
    """Returns ``GroupTask`` for the given name.

    The logical group embodied by a task is identified with its name and only 1 GroupTask will be
    created for a given name.  If the task has already been created, it will just be returned.

    :param string name: The logical name of the group.
    :param list product_type:  The names of the product types this group cooperatively produces.
    :param list flag_namespace: The parent namespace for flags registered by member tasks.
    """
    group_task = cls._GROUPS.get(name)
    if not group_task:
      class SingletonGroupTask(GroupTask):
        _MEMBER_TYPES = []

        @classmethod
        def subsystem_dependencies(cls):
          return (super(SingletonGroupTask, cls).subsystem_dependencies() +
                  tuple(s for mt in cls._member_types() for s in mt.subsystem_dependencies()))

        @classmethod
        def global_subsystems(cls):
          return (super(SingletonGroupTask, cls).global_subsystems() +
            tuple(s for mt in cls._member_types() for s in mt.global_subsystems()))

        @classmethod
        def task_subsystems(cls):
          return (super(SingletonGroupTask, cls).task_subsystems() +
            tuple(s for mt in cls._member_types() for s in mt.task_subsystems()))

        @classmethod
        def product_types(cls):
          return product_type

        # We'd prefer to get the options_scope from cls.options_scope,
        # but unfortunately that hasn't been set yet.
        options_scope = '.'.join(flag_namespace)

        @classmethod
        def known_scope_infos(cls):
          """Yields ScopeInfos for all known scopes for this task, in no particular order."""
          # We need this because task.py initializes a cache factory for every task type,
          # even if it's never used. This is slightly icky, but is better than forcing tasks
          # to explicitly call a cache setup method. And we want to kill GroupTask anyway.
          yield cls.get_scope_info()
          for subsystem in cls.task_subsystems():
            yield subsystem.get_scope_info(subscope=cls.options_scope)

          for member_type in cls._member_types():
            for scope in member_type.known_scope_infos():
              yield scope

        @classmethod
        def register_options_on_scope(cls, options):
          for member_type in cls._member_types():
            member_type.register_options_on_scope(options)

        @classmethod
        def _alternate_target_roots(cls, options, address_mapper, build_graph):
          # We don't support groups proposing alternate roots.
          # There is currently just the jvm compile group which does not need this and GroupTask
          # will be removed as part of parallelizing the RoundEngine.
          return None

        @classmethod
        def _prepare(cls, options, round_manager):
          for member_type in cls._member_types():
            member_type._prepare(options, round_manager)

        @property
        def group_name(self):
          return name

      group_task = SingletonGroupTask
      cls._GROUPS[name] = group_task

    if group_task.product_types() != product_type:
      raise ValueError('The group {!r} was already registered with product type: {!r} - refusing to '
                       'overwrite with new product type: {!r}'.format(name, group_task.product_types(),
                                                                      product_type))

    return group_task

  @classmethod
  def _member_types(cls):
    member_types = getattr(cls, '_MEMBER_TYPES')
    if member_types is None:
      raise TypeError('New GroupTask types must be created via GroupTask.named.')
    return member_types

  @classmethod
  def add_member(cls, group_member):
    """Enlists a member in this group.

    A group task delegates all its work to group members who act cooperatively on targets they
    claim. The order members are added affects the target claim process by setting the order the
    group members are asked to claim targets in on a first-come, first-served basis.
    """
    if not issubclass(group_member, GroupMember):
      raise ValueError('Only GroupMember subclasses can join a GroupTask, '
                       'given {} of type {}'.format(group_member, type(group_member)))

    group_member.options_scope = Goal.scope(cls.options_scope, group_member.name())
    cls._member_types().append(group_member)

  def __init__(self, *args, **kwargs):
    super(GroupTask, self).__init__(*args, **kwargs)

    self._group_members = [member_type(self.context, os.path.join(self.workdir, member_type.name()))
                           for member_type in self._member_types()]

  @abstractmethod
  def product_types(self):
    """GroupTask must be sub-classed to provide a product type."""

  @abstractproperty
  def group_name(self):
    """GroupTask must be sub-classed to provide a group name."""

  def execute(self):

    @contextmanager
    def workunit_for(group_member, desc):
      log_config = WorkUnit.LogConfig(
        level=group_member.get_options().level, colors=group_member.get_options().colors)
      with self.context.new_workunit(name='{}-{}'.format(group_member.name(), desc),
                                     log_config=log_config) as workunit:
        yield workunit

    with self.context.new_workunit(name=self.group_name, labels=[WorkUnitLabel.GROUP]):
      for group_member in self._group_members:
        with workunit_for(group_member, 'pre'):
          group_member.pre_execute()

      # TODO(John Sirois): implement group-level invalidation? This might be able to be done in
      # prepare_execute though by members.

      # Chunk targets from the context by group. At the end, we'll have a list of chunks to be
      # built.
      ordered_chunks = []
      chunks_by_member = defaultdict(list)
      for group_member, chunk in GroupIterator(self.context.targets(), self._group_members):
        ordered_chunks.append((group_member, chunk))
        chunks_by_member[group_member].append(chunk)

      self.context.log.debug('::: created chunks({})'.format(len(ordered_chunks)))
      for i, (group_member, goal_chunk) in enumerate(ordered_chunks):
        self.context.log.debug('  chunk({}) [flavor={}]:\n\t{}'.format(
            i, group_member.name(), '\n\t'.join(sorted(map(str, goal_chunk)))))

      # prep
      for group_member, chunks in chunks_by_member.items():
        with workunit_for(group_member, 'prepare'):
          group_member.prepare_execute(chunks)

      # chunk zig zag
      for group_member, chunk in ordered_chunks:
        with workunit_for(group_member, 'execute'):
          group_member.execute_chunk(chunk)

      # finalize
      for group_member, chunks in chunks_by_member.items():
        with workunit_for(group_member, 'finalize'):
          group_member.finalize_execute(chunks)

      # complete
      for group_member in self._group_members:
        with workunit_for(group_member, 'post'):
          group_member.post_execute()
