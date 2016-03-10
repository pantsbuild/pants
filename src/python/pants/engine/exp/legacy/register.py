# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.engine.exp.legacy.graph import LegacyBuildGraphNode, reify_legacy_graph
from pants.engine.exp.legacy.parser import TargetAdaptor
from pants.engine.exp.selectors import Select, SelectDependencies


def create_legacy_graph_tasks():
  """Create tasks to recursively parse the legacy graph."""
  return [
    # Recursively requests LegacyGraphNodes for TargetAdaptors, which will result in a
    # transitive graph walk.
    (LegacyBuildGraphNode,
     [Select(TargetAdaptor),
      SelectDependencies(LegacyBuildGraphNode, TargetAdaptor)],
     reify_legacy_graph)
  ]
