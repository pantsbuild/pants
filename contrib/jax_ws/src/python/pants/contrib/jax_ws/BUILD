# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    build_file_aliases = True,
    description = "JAX-WS Pants plugin",
    distribution_name = "pantsbuild.pants.contrib.jax_ws",
    register_goals = True,
    dependencies = [
        "contrib/jax_ws/src/python/pants/contrib/jax_ws/targets",
        "contrib/jax_ws/src/python/pants/contrib/jax_ws/tasks",
        "src/python/pants/build_graph",
        "src/python/pants/goal:task_registrar",
    ],
)
