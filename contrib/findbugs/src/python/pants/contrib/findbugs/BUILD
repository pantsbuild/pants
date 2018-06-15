# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    description = "FindBugs pants plugin",
    distribution_name = "pantsbuild.pants.contrib.findbugs",
    register_goals = True,
    dependencies = [
        "contrib/findbugs/src/python/pants/contrib/findbugs/tasks",
        "src/python/pants/build_graph",
        "src/python/pants/goal:task_registrar",
    ],
)
