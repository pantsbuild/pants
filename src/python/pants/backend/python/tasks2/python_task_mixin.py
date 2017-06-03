# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.tasks2.gather_sources import GatherSources
from pants.backend.python.tasks2.partition_targets import PartitionTargets
from pants.backend.python.tasks2.select_interpreter import SelectInterpreter


class PythonTaskMixin(object):
  """Mixin for tasks that provides convenient access to intermediate products."""

  def target_roots_partitions(self):
    partitions = self.context.products.get_data(PartitionTargets.TARGETS_PARTITIONS)
    return partitions

  def target_roots_subsets(self, partition_name):
    """Returns the subsets in the target roots partition."""
    partitions = self.context.products.get_data(PartitionTargets.TARGETS_PARTITIONS)
    return partitions[partition_name].subsets

  def interpreter_for_targets(self, partition_name, targets):
    """Returns an interpreter that is compatible with the given targets.

    All targets must be within the same subset in the partition."""
    partitions = self.context.products.get_data(PartitionTargets.TARGETS_PARTITIONS)
    interpreters = self.context.products.get_data(SelectInterpreter.PYTHON_INTERPRETERS)
    partition = partitions[partition_name]
    return interpreters[partition_name][partition.find_subset_for_targets(targets)]

  def sources_for_targets(self, partition_name, targets):
    """Returns a source pex that contains sources for all given targets.

    All targets must be within the same subset in the partition."""
    partitions = self.context.products.get_data(PartitionTargets.TARGETS_PARTITIONS)
    partition = partitions[partition_name]
    sources = self.context.products.get_data(GatherSources.PYTHON_SOURCES)
    return sources[partition_name][partition.find_subset_for_targets(targets)]
