
from pants.backend.codegen.thrift.node.apache_thrift_node_gen import ApachetThriftNodeGen
from pants.contrib.node.targets.node_thrift_library import NodeThriftLibrary
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

# def build_file_aliases():
#   return BuildFileAliases(
#     targets={
#       'node_thrift_library': NodeThriftLibrary,
#     }
#   )


def register_goals():
  task(name='thrift-node', action=ApachetThriftNodeGen).install('gen')

