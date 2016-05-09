# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.bin.goal_runner import EngineInitializer
from pants.engine.nodes import FilesystemNode


def dependencies():
  """Lists the transitive dependencies of targets under the current build root."""
  with EngineInitializer.open_legacy_graph() as (graph, addresses, _):
    for target in graph.closure([graph.get_target(a) for a in addresses]):
      print(target.address.spec)


def filemap():
  """Lists the transitive dependencies of targets under the current build root."""
  with EngineInitializer.open_legacy_graph() as (graph, addresses, _):
    for address in addresses:
      target = graph.get_target(address)
      for source in target.sources_relative_to_buildroot():
        print('{} {}'.format(source, target.address.spec))


def fsnodes():
  """Prints out all of the FilesystemNodes in the Scheduler for debugging purposes."""
  with EngineInitializer.open_legacy_graph() as (_, _, scheduler):
    for node, _ in scheduler.product_graph.completed_nodes():
      if type(node) is FilesystemNode:
        print(node)
