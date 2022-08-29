# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_sources(name="scripts", sources=["cargo", "pants"])

# We use `BUILD_ROOT` to establish the build root, rather than `./pants`, per
# https://github.com/pantsbuild/pants/pull/8105.
files(name="files", sources=["BUILD_ROOT", "pants.toml"])

python_test_utils(name="test_utils")

_local_environment(
    name="macos_local_env",
    # Avoid system Python interpreters, which tend to be broken on macOS.
    python_interpreter_search_paths=["<PYENV>"],
)

_local_environment(
    name="linux_local_env",
)

_local_environment(
    name="ci_env",
    python_interpreter_search_paths=["<PATH>"],
)
