# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    description = "Error Prone pants plugin",
    distribution_name = "pantsbuild.pants.contrib.errorprone",
    register_goals = True,
    dependencies = [
        "contrib/errorprone/src/python/pants/contrib/errorprone/tasks",
        "src/python/pants/build_graph",
        "src/python/pants/goal:task_registrar",
    ],
)
