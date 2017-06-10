# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.build_graph.target import Target
from pants.task.task import Task


class TargetsPartition(object):
  """Represents a partitioning of a set of targets into non-empty subsets."""
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

    Raises a KeyError if such target does not exist.
    """
    return self._subset_by_target[target]

  def find_subset_for_targets(self, targets):
    """Returns a single subset that contains all given targets.

    If such subset does not exists within the partition a ValueError is raised.
    """
    if not self._subsets:
      raise ValueError('No subsets.')
    if not targets:
      # Any subset will do.
      return next(iter(self._subsets))
    subset = self._subset_by_target.get(next(iter(targets)))
    if not subset or not subset.issuperset(targets):
      raise ValueError('No subset contains all targets: {}'.format(
          ' '.join(tgt.address.spec for tgt in targets)))
    return subset


class PartitionTargets(Task):
  """Generates partitions of the target roots.

  This tasks produces `TargetPartition`s. Each representing a partition of the target roots into
  non-empty disjoint subsets of targets based on a requested partitioning strategy.

  There are several supported strategies to produce a TargetPartition from a set of target roots:

  STRATEGY_MINIMAL:
      partitions the target roots into the smallest possible number of subsets such that if one target
      root depends on another, then both of them will be in the subset. This ensures
      that incompatible target roots will fall into different subsets while minimizing the number
      of chroots.
  STRATEGY_PER_TARGET:
      A partition in which Each target root will be in its own isolated subset.
      This provides maximal isolation but can be slower if there are many target
      roots.
  STRATEGY_GLOBAL:
      A partition with one single subset for all target roots. This means that all target
      roots need to be compatible with each other.

  The strategies that are requested via require_data() will be provided.  In addition a product
  TARGETS_PARTITION is provided which is a map between the requested strategy and the
  partition.
  """

  TARGETS_PARTITIONS = 'targets_partitions'
  STRATEGY_MINIMAL = 'targets_partition_minimal'
  STRATEGY_PER_TARGET = 'targets_partition_per_target'
  STRATEGY_GLOBAL = 'targets_partition_global'

  @classmethod
  def product_types(cls):
    return [cls.TARGETS_PARTITIONS,
            cls.STRATEGY_MINIMAL,
            cls.STRATEGY_PER_TARGET,
            cls.STRATEGY_GLOBAL]

  @classmethod
  def register_options(cls, register):
    super(PartitionTargets, cls).register_options(register)
    return
    register(
        '--strategy',
        choices=[cls.STRATEGY_MINIMAL, cls.STRATEGY_PER_TARGET, cls.STRATEGY_GLOBAL],
        help='Specifies how to partition the targets into subsets.',
        default=cls.STRATEGY_GLOBAL)

  @classmethod
  def _minimal_partition(cls, targets):
    subsets_by_head = {}

    closures = {target: target.closure() for target in targets}

    for target in targets:
      is_head = all(target not in closures[other] or other == target
                   for other in targets)
      if is_head:
        subsets_by_head[target] = {target}

    for target in targets:
      for head in subsets_by_head:
        if target in closures[head]:
          subsets_by_head[head].add(target)
          break
      else:
        assert False, 'Target not in closure of any head.'

    return TargetsPartition(subsets_by_head.values())

  @classmethod
  def _per_target_partition(cls, targets):
    return TargetsPartition([[t] for t in targets])

  @classmethod
  def _global_partition(cls, targets):
    return TargetsPartition([targets] if targets else [])

  def execute(self):
    partitions = self.context.products.register_data(self.TARGETS_PARTITIONS, {})
    strategies = {
        self.STRATEGY_MINIMAL: self._minimal_partition,
        self.STRATEGY_PER_TARGET: self._per_target_partition,
        self.STRATEGY_GLOBAL: self._global_partition,
    }

    for product_name, get_partition in strategies.items():
      if self.context.products.is_required_data(product_name):
        partitions[product_name] = self.context.products.register_data(
            product_name, get_partition(self.context.target_roots))
