# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    description = "Additional python lints and checks.",
    distribution_name = "pantsbuild.pants.contrib.python.checks",
    register_goals = True,
    dependencies = [
        "contrib/python/src/python/pants/contrib/python/checks/tasks",
        "contrib/python/src/python/pants/contrib/python/checks/tasks/checkstyle:all",
        "src/python/pants/goal:task_registrar",
    ],
)
