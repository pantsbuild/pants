# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    build_file_aliases = True,
    description = "Go language support for pants.",
    distribution_name = "pantsbuild.pants.contrib.go",
    register_goals = True,
    dependencies = [
        "contrib/go/src/python/pants/contrib/go/targets",
        "contrib/go/src/python/pants/contrib/go/tasks",
        "src/python/pants/build_graph",
        "src/python/pants/goal:task_registrar",
    ],
)
