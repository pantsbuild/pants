# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_sources(name="scripts", sources=["cargo", "pants"])

# We use `BUILD_ROOT` to establish the build root, rather than `./pants`, per
# https://github.com/pantsbuild/pants/pull/8105.
files(name="files", sources=["BUILD_ROOT", "pants.toml"])

python_test_utils(name="test_utils")

# Used for experimenting with the new Docker support.
docker_environment(
    name="docker_env",
    image="python:3.9",
    python_bootstrap_search_path=["<PATH>"],
)

# See `build-support/reapi-sample-server/README.md` for information on how to use this environment
# for internal testing.
remote_environment(
    name="buildgrid_remote",
    python_bootstrap_search_path=["<PATH>"],
)

files(
    name="all-__init__.py-files",
    sources=[
        "**/__init__.py",
        # These are explicit namespace packages
        "!src/python/pants/__init__.py",
        "!src/python/pants/testutil/__init__.py",
    ]
)

experimental_test_shell_command(
    name="Check empty init files",
    command="test -r $CHROOT/some-data-file.txt",
    tools=["test"],
    execution_dependencies=[":all-__init__.py-files"],
)
