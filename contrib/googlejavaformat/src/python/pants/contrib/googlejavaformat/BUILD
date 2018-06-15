# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(sources = ["googlejavaformat.py"])

contrib_plugin(
    name = "plugin",
    additional_classifiers = [
        "Topic :: Software Development :: Pre-processors",
    ],
    description = "Google Java Format code formatter pants plugins.",
    distribution_name = "pantsbuild.pants.contrib.googlejavaformat",
    register_goals = True,
    dependencies = [
        ":googlejavaformat",
        "src/python/pants/goal:task_registrar",
    ],
)
