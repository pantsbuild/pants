# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

python_library()

python_tests(
  name="tests",
  dependencies=[
    # Used by `options_bootstrapper_test` and `config_test`.
    '//:build_root',
    '//:pants_toml',
  ],
  timeout=300,
)
