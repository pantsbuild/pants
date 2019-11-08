# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.goal.task_registrar import TaskRegistrar as task

from pants.contrib.jax_ws.targets.jax_ws_library import JaxWsLibrary
from pants.contrib.jax_ws.tasks.jax_ws_gen import JaxWsGen


def build_file_aliases():
  return BuildFileAliases(
    targets={
      'jax_ws_library': JaxWsLibrary,
    }
  )


def register_goals():
  task(name='jax-ws', action=JaxWsGen).install('gen')
