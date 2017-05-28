# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.build_graph.target import Target
from pants.task.task import Task


class TargetsPartition(object):
  """Represents a grouping of targets into non-empty subsets."""
  def __init__(self, subsets):
    """Constructs a new TargetsPartition from a given collection of subsets.

    :param subsets: an iterable of iterables of targets.
    """
    if any(len(subset) == 0 for subset in subsets):
      raise ValueError('Subsets must be non-empty.')
    self._subsets = frozenset(frozenset(subset) for subset in subsets)
    if self._subsets and (
        len(frozenset.union(*self._subsets)) != sum(len(subset) for subset in self._subsets)):
      raise ValueError('Subsets must be disjoint.')
    self._subset_by_target = {target: subset for subset in self._subsets for target in subset}

  @property
  def subsets(self):
    return self._subsets

  def find_subset_for_target(self, target):
    """Returns a subset containing the given targets.

    Raises a KeyError if such target does not exist."""
    return self._subset_by_target[target]

  def find_subset_for_targets(self, targets):
    """Returns a single subset that contains all given targets.

    If such subset does not exists within the partition a ValueError is raised."""
    if not self._subsets:
      raise ValueError('No subsets.')
    if not targets:
      # Any subset will do
      return next(iter(self._subsets))
    subset = self._subset_by_target.get(next(iter(targets)))
    if not subset or not subset.issuperset(set(targets)):
      raise ValueError('No subset contains all targets')
    return subset


class PartitionTargets(Task):
  TARGETS_PARTITION = 'targets_partition'

  STRATEGY_MINIMAL = 'minimal'
  STRATEGY_PER_TARGET = 'per_target'
  STRATEGY_GLOBAL = 'global'

  @classmethod
  def product_types(cls):
    return [cls.TARGETS_PARTITION]

  @classmethod
  def register_options(cls, register):
    super(PartitionTargets, cls).register_options(register)
    register(
        '--strategy',
        choices=[cls.STRATEGY_MINIMAL, cls.STRATEGY_PER_TARGET, cls.STRATEGY_GLOBAL],
        help='Specifies how to partition the targets into subsets. '
             '"global": creates a single subset for all target roots. This means a single '
             'source tree, interpreter and external requirements pex will be provided for all '
             'targets, and therefore the targets must be compatible with each other. '
             '"minimal": groups the target roots into the smallest possible number of subsets '
             'such that if one target root depends on another, then both of them will be in the '
             'subset. This ensures that incompatible target roots will fall into different subsets '
             'while minimizing the number of chroots. '
             '"per_target": each target root will be in its own isolated group. This provides '
             'maximal isolation but can be slower if there are many target roots.',
        default=cls.STRATEGY_GLOBAL)

  @classmethod
  def _minimal_partition(cls, targets):
    groups_by_head = {}

    closures = {target: target.closure() for target in targets}

    for target in targets:
      is_head = all(target not in closures[other] or other == target
                   for other in targets)
      if is_head:
        groups_by_head[target] = {target}

    for target in targets:
      for head in groups_by_head:
        if target in closures[head]:
          groups_by_head[head].add(target)
          break
      else:
        assert False, 'Target not in closure of any head.'

    return TargetsPartition(groups_by_head.values())

  @classmethod
  def _per_target_partition(cls, targets):
    return TargetsPartition([[t] for t in targets])

  @classmethod
  def _global_partition(cls, targets):
    return TargetsPartition([targets] if targets else [])

  def execute(self):
    strategy = self.get_options().strategy
    if strategy == self.STRATEGY_MINIMAL:
      partition = self._minimal_partition(self.context.target_roots)
    elif strategy == self.STRATEGY_PER_TARGET:
      partition = self._per_target_partition(self.context.target_roots)
    elif strategy == self.STRATEGY_GLOBAL:
      partition = self._global_partition(self.context.target_roots)
    else:
      assert False, 'Unexpected partitioning strategy.'
    self.context.products.get_data(self.TARGETS_PARTITION, lambda: partition)
