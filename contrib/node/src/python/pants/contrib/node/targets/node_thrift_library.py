from pants.contrib.node.targets.node_module import NodeModule


class NodeThriftLibrary(NodeModule):
  """
  A Node library generated from Thrift IDL Files
  """

  def __init__(self, **kwargs):
    super().__init__(**kwargs)
