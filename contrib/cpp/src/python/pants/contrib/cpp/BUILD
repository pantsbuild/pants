# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    build_file_aliases = True,
    description = "C++ pants plugin.",
    distribution_name = "pantsbuild.pants.contrib.cpp",
    register_goals = True,
    dependencies = [
        "contrib/cpp/src/python/pants/contrib/cpp/targets",
        "contrib/cpp/src/python/pants/contrib/cpp/tasks",
        "contrib/cpp/src/python/pants/contrib/cpp/toolchain",
        "src/python/pants/build_graph",
        "src/python/pants/goal:task_registrar",
    ],
)
