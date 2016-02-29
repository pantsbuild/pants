# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.build_graph.build_graph import BuildGraph
from pants.engine.exp.legacy.parsers import LegacyPythonCallbacksParser, TargetAdaptor
from pants.engine.exp.selectors import Select, SelectDependencies, SelectLiteral
from pants.util.objects import datatype


class ExpGraph(BuildGraph):
  def __init__(self):
    pass


class LegacyBuildGraphNode(datatype('LegacyGraphNode', ['target', 'target_cls', 'dependency_addresses'])):
  """A Node to represent a node in the legacy BuildGraph.

  A facade implementing the legacy BuildGraph would inspect only these entries in the ProductGraph.
  """


def reify_legacy_graph(legacy_target, dependency_nodes, symbol_table_cls):
  """Given a TargetAdaptor and LegacyBuildGraphNodes for its deps, return a LegacyBuildGraphNode."""
  # Instantiate the Target from the TargetAdaptor struct.
  target = legacy_target
  target_cls = symbol_table_cls.aliases().target_types.get(target.type_alias, None)
  return LegacyBuildGraphNode(target, target_cls, [node.target.address for node in dependency_nodes])


def create_legacy_graph_tasks(symbol_table_cls_key):
  """Create tasks to recursively parse the legacy graph."""
  return [
      # Given a TargetAdaptor and its dependencies, construct a Target.
      (LegacyBuildGraphNode,
       [Select(TargetAdaptor),
        SelectDependencies(LegacyBuildGraphNode, TargetAdaptor),
        SelectLiteral(symbol_table_cls_key, type)],
       reify_legacy_graph)
    ]
