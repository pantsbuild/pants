# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    description = "mypy static type analyzer",
    distribution_name = "pantsbuild.pants.contrib.mypy",
    register_goals = True,
    dependencies = [
        "contrib/mypy/src/python/pants/contrib/mypy/tasks",
        "src/python/pants/goal:task_registrar",
    ],
)
