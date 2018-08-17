# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.contrib.node.tasks.node_paths import NodePaths


class NodePathsLocal(NodePaths):
  """Maps Node package targets to their local NODE_PATH chroot."""
