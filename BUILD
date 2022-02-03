# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_sources(name="scripts", sources=["cargo", "pants"], description="Nothing much.")

# We use `BUILD_ROOT` to establish the build root, rather than `./pants`, per
# https://github.com/pantsbuild/pants/pull/8105.
files(
    name="files",
    sources=["BUILD_ROOT", ".gitignore", "pants.toml"],
    tags=["testing", "this"],
    description="""
We use `BUILD_ROOT` to establish the build root, rather than `./pants`, per
https://github.com/pantsbuild/pants/pull/8105.
""",
)
