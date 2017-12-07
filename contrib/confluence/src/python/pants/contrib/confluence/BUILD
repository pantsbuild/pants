# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

contrib_plugin(
    name = "plugin",
    build_file_aliases = True,
    description = "Confluence pants plugin",
    distribution_name = "pantsbuild.pants.contrib.confluence",
    register_goals = True,
    dependencies = [
        "contrib/confluence/src/python/pants/contrib/confluence/targets",
        "contrib/confluence/src/python/pants/contrib/confluence/tasks",
        "contrib/confluence/src/python/pants/contrib/confluence/util",
        "src/python/pants/build_graph",
    ],
)
