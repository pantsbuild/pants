# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
    name="lib",
    sources=["name.py", "setup.py"],
)

resources(name="impl", sources=["*.c"])

python_distribution(
    name = "dist",
    dependencies = [":impl", ":lib"],
    provides = python_artifact(
        name = "native",
        version = "2.3.4",
        setup_script='setup.py',
    ),
    setup_py_commands = ["bdist_wheel",],
)

python_library(
    name="main_lib",
    sources=["main.py"],
)

pex_binary(
    name="main",
    entry_point='main.py',
    dependencies=[":dist", ":main_lib"],
)
