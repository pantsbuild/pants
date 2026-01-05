# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
    name="tests",
    # These tests no longer work on the current CI environment.  How
    # they worked before is poorly understood See
    # https://github.com/pantsbuild/pants/pull/22704
    skip_tests=True,
    extra_env_vars=["RUSTUP_HOME"],
)
