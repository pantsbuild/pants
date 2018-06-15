# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(sources = [
    "java_thrifty_gen.py",
    "java_thrifty_library.py",
])

contrib_plugin(
    name = "plugin",
    additional_classifiers = [
        "Topic :: Software Development :: Code Generators",
    ],
    build_file_aliases = True,
    description = "Microsoft Thrifty thrift generator pants plugins.",
    distribution_name = "pantsbuild.pants.contrib.thrifty",
    register_goals = True,
    dependencies = [
        ":thrifty",
        "src/python/pants/goal:task_registrar",
    ],
)
