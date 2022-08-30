# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

shell_sources(name="scripts", sources=["cargo", "pants"])

# We use `BUILD_ROOT` to establish the build root, rather than `./pants`, per
# https://github.com/pantsbuild/pants/pull/8105.
files(name="files", sources=["BUILD_ROOT", "pants.toml"])

python_test_utils(name="test_utils")

# TODO(#7735): Add a macos_local_env that sets `python_interpreter_search_paths=["<PYENV>"]`, after
#   figuring out why our Build Wheels Mac job is failing when this is set:
#   https://github.com/pantsbuild/pants/runs/8082954359?check_suite_focus=true#step:9:657
_local_environment(
    name="local_env",
)
