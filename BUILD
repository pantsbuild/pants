# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_sources(name="scripts", sources=["cargo", "pants"])

# We use `BUILD_ROOT` to establish the build root, rather than `./pants`, per
# https://github.com/pantsbuild/pants/pull/8105.
files(name="files", sources=["BUILD_ROOT", "pants.toml"])

python_test_utils(name="test_utils")

_local_environment(
    name="default_env",
)

_local_environment(
    name="macos_local_env",
    compatible_platforms=["macos_arm64", "macos_x86_64"],
    # Avoid system Python interpreters, which tend to be broken on macOS.
    python_bootstrap_search_path=["<PYENV>"],
)

# Used for experimenting with the new Docker support.
_docker_environment(
    name="docker_env",
    image="python:3.9",
)
