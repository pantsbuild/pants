# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.contrib.node.resolvers.node_resolver_base import NodeResolverBase


class NodePreinstalledModuleResolver(NodeResolverBase):

  def resolve_target(self, node_task, target, results_dir, node_paths):
    """Resolve a NodePackage target."""
