# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    build_file_aliases = True,
    description = "Node.js support for pants.",
    distribution_name = "pantsbuild.pants.contrib.node",
    global_subsystems = True,
    register_goals = True,
    dependencies = [
        "contrib/node/src/python/pants/contrib/node/subsystems/resolvers",
        "contrib/node/src/python/pants/contrib/node/targets",
        "contrib/node/src/python/pants/contrib/node/tasks",
        "src/python/pants/build_graph",
        "src/python/pants/goal:task_registrar",
    ],
)
