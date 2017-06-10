# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.partition_targets import PartitionTargets
from pants.backend.python.tasks2.select_interpreter import SelectInterpreter
from pants.task.task import Task


class PythonTask(Task):
  """Base class for tasks that provides convenient access to pyprep products.

  During the pyprep goal, the Python pipeline computes partitions of the targets. Then it
  selects interpreters and resolves requirements for each subset in each of computed partitions.

  This base class provides convenient access to these products.
  """

  def target_roots_partitions(self):
    partitions = self.context.products.get_data(PartitionTargets.TARGETS_PARTITIONS)
    return partitions

  def target_roots_subsets(self, partition_name):
    """Returns the subsets in the target roots partition."""
    partitions = self.context.products.get_data(PartitionTargets.TARGETS_PARTITIONS)
    return partitions[partition_name].subsets

  def find_subset_for_targets(self, partition_name, targets):
    """Return a subset of the partition containing all targets."""
    partitions = self.context.products.get_data(PartitionTargets.TARGETS_PARTITIONS)
    partition = partitions[partition_name]
    return partition.find_subset_for_targets(targets)

  def interpreter_for_targets(self, partition_name, targets):
    """Returns an interpreter that is compatible with the given targets.

    All targets must be within the same subset in the partition.
    """
    interpreters = self.context.products.get_data(SelectInterpreter.PYTHON_INTERPRETERS)
    return interpreters[partition_name][self.find_subset_for_targets(partition_name, targets)]

  def sources_for_targets(self, partition_name, targets):
    """Returns a source pex that contains sources for all given targets.

    All targets must be within the same subset in the partition.
    """
    sources = self.context.products.get_data(GatherSources.PYTHON_SOURCES)
    return sources[partition_name][self.find_subset_for_targets(partition_name, targets)]
