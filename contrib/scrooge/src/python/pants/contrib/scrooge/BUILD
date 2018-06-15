# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    additional_classifiers = [
        "Topic :: Software Development :: Code Generators",
    ],
    description = "Scrooge thrift generator pants plugins.",
    distribution_name = "pantsbuild.pants.contrib.scrooge",
    register_goals = True,
    dependencies = [
        "contrib/scrooge/src/python/pants/contrib/scrooge/tasks",
        "src/python/pants/goal:task_registrar",
    ],
)
