# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
    name = "plugin",
    sources = [],
    provides = contrib_setup_py(
        name = "pantsbuild.pants.contrib.buildgen",
        additional_classifiers = [
            "Topic :: Software Development :: Code Generators",
        ],
        description = "Automatic manipulation of BUILD dependencies based on source analysis.",
    ),
    dependencies = [
        ":build_file_manipulator",
    ],
)

python_library(
    name = "build_file_manipulator",
    sources = ["build_file_manipulator.py"],
    dependencies = [
        "src/python/pants/build_graph",
    ],
)
