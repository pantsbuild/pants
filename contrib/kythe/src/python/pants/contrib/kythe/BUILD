# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    description = "Kythe support for pants.",
    distribution_name = "pantsbuild.pants.contrib.kythe",
    register_goals = True,
    dependencies = [
        "contrib/kythe/src/python/pants/contrib/kythe/tasks",
        "src/python/pants/goal:task_registrar",
    ],
)
