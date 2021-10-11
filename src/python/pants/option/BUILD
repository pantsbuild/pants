# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_sources()

python_tests(
  name="tests",
  dependencies=[
    # Used by `options_bootstrapper_test` and `config_test`.
    '//BUILD_ROOT:files',
    '//pants.toml:files',
  ],
  timeout=300,
)
