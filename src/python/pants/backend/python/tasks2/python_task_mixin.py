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

  def target_roots_subsets(self):
    """Returns the subsets in the target roots partition."""
    partition = self.context.products.get_data(PartitionTargets.TARGETS_PARTITION)
    return partition.subsets

  def interpreter_for_targets(self, targets):
    """Returns an interpreter that is compatible with the given targets.

    All targets must be within the same subset in the partition."""
    partition = self.context.products.get_data(PartitionTargets.TARGETS_PARTITION)
    interpreters = self.context.products.get_data(SelectInterpreter.PYTHON_INTERPRETERS)
    return interpreters[partition.find_subset_for_targets(targets)]

  def sources_for_targets(self, targets):
    """Returns a source pex that contains sources for all given targets.

    All targets must be within the same subset in the partition."""
    partition = self.context.products.get_data(PartitionTargets.TARGETS_PARTITION)
    sources = self.context.products.get_data(GatherSources.PYTHON_SOURCES)
    return sources[partition.find_subset_for_targets(targets)]
