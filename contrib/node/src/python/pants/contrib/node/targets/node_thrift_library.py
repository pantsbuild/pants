# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.contrib.node.targets.node_module import NodeModule


class NodeThriftLibrary(NodeModule):
  """
  A Node library generated from Thrift IDL Files
  """
  # def __init__(self, **kwargs):
  #   super().__init__(**kwargs)
  #   if 'package.json' in self.payload.sources:
  #     raise Exception("Use default generated package.json.")

  #   if 'yarn.lock' in self.payload.sources:
  #     raise Exception("Use default generated yarn.lock.")
