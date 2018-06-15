# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

# Like Hello world, but built with a python_dist.
# python_dist allows you to use setup.py to depend on C/C++ extensions.

python_dist(
    name = "hello",
    sources = [
        "hello_package/__init__.py",
        "hello_package/hello.py",
        "setup.py",
    ],
    setup_requires = [
        "examples/src/python/example/python_distribution/hello/setup_requires:setup_requires_lib",
    ],
)

python_requirement_library(
    name = "setup_requires_lib",
    requirements = [
        python_requirement("pycountry==18.5.20"),
    ],
)

python_binary(
    name = "main",
    source = "main.py",
    platforms = ["current"],
    dependencies = [
        ":hello",
    ],
)
