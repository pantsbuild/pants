# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    description = "Plugin to manipulate and refactor BUILD files and targets",
    distribution_name = "pantsbuild.pants.contrib.buildrefactor",
    register_goals = True,
    dependencies = [
        ":buildrefactor",
    ],
)

python_library(
    dependencies = [
        "src/python/pants/base:build_environment",
        "src/python/pants/base:exceptions",
        "src/python/pants/binaries",
    ],
)
