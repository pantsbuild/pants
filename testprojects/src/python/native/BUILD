# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library(
)

resources(name="impl", sources=["*.c"])

python_distribution(
    name = "dist",
    dependencies = [":impl", ":native"],
    provides = setup_py(
        name = "native",
        version = "2.3.4",
        setup_script='testprojects/src/python/native/setup.py',
    ),
    setup_py_commands = ["bdist_wheel",]
)

