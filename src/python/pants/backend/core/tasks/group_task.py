# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from abc import abstractmethod, abstractproperty
from collections import defaultdict
import os

from pants.backend.core.tasks.check_exclusives import ExclusivesMapping
from pants.backend.core.tasks.task import TaskBase, Task
from pants.base.build_graph import sort_targets
from pants.base.workunit import WorkUnit
from pants.goal.goal import Mkflag


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

  def prepare_execute(self, chunks):
    """Prepare to execute the group action across the given target chunks.

    Chunks are guaranteed to be presented in least dependent to most dependent order and to contain
    only directly or indirectly invalidated targets.

    :param list chunks: A list of chunks, each chunk being a list of targets that should be
      processed together.
    """

  @abstractmethod
  def execute_chunk(self, targets):
    """Process the targets in this chunk.

    This chunk or targets' dependencies are guaranteed to have been processed in a prior
    ``execute_chunk`` round by some group member - possibly this one.

    :param list targets: A list of targets that should be processed together (ie: 1 chunk)
    """

  def post_execute(self):
    """Called when all invalid targets claimed by the group have been processed."""


class GroupIterator(object):
  """Iterates the goals in a group over the chunks they own."""

  @staticmethod
  def coalesce_targets(targets, discriminator):
    """Returns a list of Targets that `targets` depend on sorted from most dependent to least.

    The targets are grouped where possible by target type as categorized by the given discriminator.

    This algorithm was historically known as the "bang" algorithm from a time when it was
    optionally enabled by appending a '!' (bang) to the command line target.
    """

    sorted_targets = filter(discriminator, sort_targets(targets))

    # can do no better for any of these:
    # []
    # [a]
    # [a,b]
    if len(sorted_targets) <= 2:
      return sorted_targets

    # For these, we'd like to coalesce if possible, like:
    # [a,b,a,c,a,c] -> [a,a,a,b,c,c]
    # adopt a quadratic worst case solution, when we find a type change edge, scan forward for
    # the opposite edge and then try to swap dependency pairs to move the type back left to its
    # grouping.  If the leftwards migration fails due to a dependency constraint, we just stop
    # and move on leaving "type islands".
    current_type = None

    # main scan left to right no backtracking
    for i in range(len(sorted_targets) - 1):
      current_target = sorted_targets[i]
      if current_type != discriminator(current_target):
        scanned_back = False

        # scan ahead for next type match
        for j in range(i + 1, len(sorted_targets)):
          look_ahead_target = sorted_targets[j]
          if current_type == discriminator(look_ahead_target):
            scanned_back = True

            # swap this guy as far back as we can
            for k in range(j, i, -1):
              previous_target = sorted_targets[k - 1]
              mismatching_types = current_type != discriminator(previous_target)
              not_a_dependency = look_ahead_target not in previous_target.closure()
              if mismatching_types and not_a_dependency:
                sorted_targets[k] = sorted_targets[k - 1]
                sorted_targets[k - 1] = look_ahead_target
              else:
                break  # out of k

            break  # out of j

        if not scanned_back:  # done with coalescing the current type, move on to next
          current_type = discriminator(current_target)

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
    def discriminator(tgt):
      for member in self._group_members:
        if member.select(tgt):
          return member
      return None

    coalesced = list(reversed(self.coalesce_targets(self._targets, discriminator)))

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


class ExclusivesIterator(object):
  """Iterates over groups of compatible targets."""

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
    :param string product_type:  The name of the product type this group cooperatively produces.
    :param list flag_namespace:
    """
    group_task = cls._GROUPS.get(name)
    if not group_task:
      class SingletonGroupTask(GroupTask):
        _MEMBER_TYPES = []

        @classmethod
        def setup_parser(cls, option_group, args, mkflag):
          base_namespace = flag_namespace or mkflag.namespace
          for member_type in cls._member_types():
            member_namespace = base_namespace + [member_type.name()]
            mkflag = Mkflag(*member_namespace)
            member_type.setup_parser(option_group, args, mkflag)

        @classmethod
        def product_types(cls):
          return product_type

        @property
        def group_name(self):
          return name

      group_task = SingletonGroupTask
      cls._GROUPS[name] = group_task

    if group_task.product_types() != product_type:
      raise ValueError('The group %r was already registered with product type: %r - refusing to '
                       'overwrite with new product type: %r' % (name, group_task.product_types(),
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
                       'given %s of type %s' % (group_member, type(group_member)))

    cls._member_types().append(group_member)

  def __init__(self, context, workdir):
    super(GroupTask, self).__init__(context, workdir)

    self._group_members = []

  @abstractmethod
  def product_types(self):
    """GroupTask must be sub-classed to provide a product type."""

  @abstractproperty
  def group_name(self):
    """GroupTask must be sub-classed to provide a group name."""

  def prepare(self, round_manager):
    round_manager.require_data('exclusives_groups')
    for member_type in self._member_types():
      group_member = member_type(self.context, os.path.join(self.workdir, member_type.name()))
      group_member.prepare(round_manager)
      self._group_members.append(group_member)

  def execute(self):
    with self.context.new_workunit(name=self.group_name, labels=[WorkUnit.GROUP]):
      # TODO(John Sirois): implement group-level invalidation? This might be able to be done in
      # prepare_execute though by members.

      # First, divide the set of all targets to be built into compatible chunks, based
      # on their declared exclusives. Then, for each chunk of compatible exclusives, do
      # further sub-chunking. At the end, we'll have a list of chunks to be built,
      # which will go through the chunks of each exclusives-compatible group separately.

      # TODO(markcc); chunks with incompatible exclusives require separate ivy resolves.
      # Either interleave the ivy task in this group so that it runs once for each batch of
      # chunks with compatible exclusives, or make the compilation tasks do their own ivy
      # resolves for each batch of targets they're asked to compile.

      ordered_chunks = []
      chunks_by_member = defaultdict(list)

      # TODO(John Sirois): GroupTask is currently dependent on CheckExclusives but this
      # is wired indirectly in register.py.  Kill the dependency and push the exclusives bit
      # into the GroupMembers that need it or else find a clean way to programatically depend
      # on CheckExclusives.
      exclusives = self.context.products.get_data('exclusives_groups')
      for exclusive_chunk in ExclusivesIterator(exclusives):
        for group_member, chunk in GroupIterator(exclusive_chunk, self._group_members):
          ordered_chunks.append((group_member, chunk))
          chunks_by_member[group_member].append(chunk)

      self.context.log.debug('::: created chunks(%d)' % len(ordered_chunks))
      for i, (group_member, goal_chunk) in enumerate(ordered_chunks):
        self.context.log.debug('  chunk(%d) [flavor=%s]:\n\t%s' % (
            i, group_member.name(), '\n\t'.join(sorted(map(str, goal_chunk)))))

      # prep
      for group_member, chunks in chunks_by_member.items():
        group_member.prepare_execute(chunks)

      # chunk zig zag
      for group_member, chunk in ordered_chunks:
        group_member.execute_chunk(chunk)

      # finalize
      for group_member in self._group_members:
        group_member.post_execute()
