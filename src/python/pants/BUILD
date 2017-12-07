# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

target(
    description = "An alias for the pants binary target.",
    dependencies = [
        "src/python/pants/bin:pants",
    ],
)

python_library(
    name = "pants-packaged",
    sources = [],
    provides = pants_setup_py(
        name = "pantsbuild.pants",
        description = "A scalable build tool for large, complex, heterogeneous repos.",
        namespace_packages = [
            "pants",
            "pants.backend",
        ],
    ).with_binaries(
        pants = "src/python/pants/bin:pants",
    ),
    dependencies = [
        ":version",
    ],
)

page(
    name = "readme",
    source = "README.md",
)

python_library(
    name = "version",
    sources = ["version.py"],
    dependencies = [
        ":version-resource",
        "3rdparty/python:packaging",
    ],
)

resources(
    name = "version-resource",
    sources = ["VERSION"],
)

page(
    name = "changelog",
    source = "CHANGELOG.md",
    description = """
This file is no longer a changelog, but remains in this location in order to avoid breaking
older changelog links unnecessarily. Could consider removing it by 2.0.x, perhaps.
""",
    links = [
        "src/python/pants/notes:notes-1.0.x",
        "src/python/pants/notes:notes-master",
    ],
)
