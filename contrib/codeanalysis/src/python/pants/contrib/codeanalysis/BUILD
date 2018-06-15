# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    description = "Support for various code analysis tools in Pants.",
    distribution_name = "pantsbuild.pants.contrib.codeanalysis",
    register_goals = True,
    dependencies = [
        "contrib/codeanalysis/src/python/pants/contrib/codeanalysis/tasks",
        "src/python/pants/build_graph",
        "src/python/pants/goal:task_registrar",
    ],
)
